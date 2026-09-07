"""Arc-Orc-Rev Pipeline Runner.

Coordinates the state machine: Architect -> Orchestrator -> Reviewer -> Security Gate -> Dispatch.
Implements RFC v7 §2, §4.7, §6.1, and §10.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import uuid
from typing import Any, Dict, List, Optional

# Ensure sibling modules in sysadmin are importable
sys.path.insert(0, os.path.dirname(__file__))

from mcp_core.workspace import WORKSPACE_ROOT
from mcp_core.context_store import ContextStore
from mcp_core.transport import send_terminal_mcp
from mcp_ollama.server import handle_chat
from validator import validate_annotated_plan

# Sampling profiles per taxonomy role (RFC v7 §4.7)
SMMP_PROFILES: Dict[str, Dict[str, Any]] = {
    "architect": {"temperature": 0.25, "top_p": 0.90, "description": "Creative decomposition & alternatives"},
    "orchestrator": {"temperature": 0.10, "top_p": 0.80, "description": "Deterministic DAG construction & scheduling"},
    "reviewer": {"temperature": 0.00, "top_p": 1.00, "description": "Greedy decoding for strict, reproducible auditing"},
    "security": {"temperature": 0.00, "top_p": 1.00, "description": "Greedy decoding for adversarial STRIDE threat modeling"},
    "coder": {"temperature": 0.05, "top_p": 0.85, "description": "High-precision code syntax & ShellCheck compliance"},
    "sysadmin": {"temperature": 0.00, "top_p": 1.00, "description": "Zero-hallucination bash & systemd command generation"},
}


class PipelineState:
    """Tracks the mutable state of a single pipeline run."""

    def __init__(self, run_id: str, original_prompt: str):
        self.run_id = run_id
        self.original_prompt = original_prompt
        self.status = "running"
        self.current_phase = "architect"
        self.architect_revisions_used = 0
        self.orchestrator_revisions_used = 0
        self.architect_budget = 3
        self.orchestrator_budget = 3
        self.messages: Dict[str, Any] = {}
        self.tasks: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []
        self.prior_plan_hash: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to state.json schema (§6.1)."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "original_prompt": self.original_prompt,
            "architect_revisions_used": self.architect_revisions_used,
            "orchestrator_revisions_used": self.orchestrator_revisions_used,
            "current_phase": self.current_phase,
            "messages": {
                k: f"runs/{self.run_id}/messages/{k}.json" if isinstance(v, dict) else v
                for k, v in self.messages.items()
            },
            "tasks": self.tasks,
            "events": self.events,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineState":
        """Deserialize from state.json for --resume support."""
        state = cls(
            run_id=data["run_id"],
            original_prompt=data.get("original_prompt", ""),
        )
        state.status = data.get("status", "running")
        state.current_phase = data.get("current_phase", "architect")
        state.architect_revisions_used = data.get("architect_revisions_used", 0)
        state.orchestrator_revisions_used = data.get("orchestrator_revisions_used", 0)
        state.tasks = data.get("tasks", {})
        state.events = data.get("events", [])
        state.messages = data.get("messages", {})
        return state

    def add_event(self, event_type: str, detail: str, pillar: Optional[str] = None) -> None:
        """Append a timestamped event to self.events."""
        self.events.append({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": event_type,
            "pillar": pillar,
            "detail": detail,
        })


def load_role_prompt(role: str) -> str:
    """Load system prompt markdown for a role from sysadmin/prompts/roles/."""
    path = os.path.join(WORKSPACE_ROOT, "sysadmin", "prompts", "roles", f"{role}.md")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return f"You are the {role.capitalize()}. Output a single valid JSON message matching schema version 2.0."


def parse_llm_json(response: str) -> dict:
    """Parse JSON response from Ollama, stripping telemetry stats and markdown code blocks."""
    # Strip telemetry stats footer appended by handle_chat
    clean = response.split("\n\n---\n")[0].strip()

    # Match ```json ... ``` or ``` ... ```
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.DOTALL)
    if code_block:
        candidate = code_block.group(1).strip()
    else:
        # Fallback to outer brackets
        start = clean.find("{")
        end = clean.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = clean[start : end + 1].strip()
        else:
            candidate = clean

    return json.loads(candidate)


def stage_chat(
    role: str,
    system_prompt: str,
    user_content: str,
    model: str = "winter-prime:latest",
    tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Call Ollama via handle_chat with SMMP profile applied + terminal-mcp streaming."""
    profile = SMMP_PROFILES.get(role, {"temperature": 0.1, "top_p": 0.9})
    send_terminal_mcp(
        f"\n🔄 [{role.upper()}] Starting phase... (temp={profile['temperature']}, top_p={profile['top_p']})"
    )

    response = handle_chat(
        model=model,
        prompt=user_content,
        system_prompt=system_prompt,
        tools=tools,
        temperature=profile["temperature"],
        top_p=profile["top_p"],
    )

    summary = response[:800] if len(response) > 800 else response
    send_terminal_mcp(f"\n✅ [{role.upper()}] Complete\n{summary}")
    return response


def run_architect(state: PipelineState, store: ContextStore, model: str = "winter-prime:latest") -> str:
    """Architect Phase: Decomposes user's prompt into tasks (PlanMessage)."""
    if state.architect_revisions_used >= state.architect_budget:
        state.status = "aborted"
        state.add_event("budget_exhausted", "Architect revision budget exhausted", "3")
        return "aborted"

    sys_prompt = load_role_prompt("architect")
    user_payload: Dict[str, Any] = {
        "run_id": state.run_id,
        "original_prompt": state.original_prompt,
        "revision": state.architect_revisions_used,
    }
    if state.architect_revisions_used > 0:
        feedback = state.messages.get("review_verdict") or state.messages.get("security_verdict")
        if feedback:
            user_payload["prior_feedback"] = feedback

    raw_response = stage_chat(
        role="architect",
        system_prompt=sys_prompt,
        user_content=json.dumps(user_payload, indent=2),
        model=model,
    )
    plan = parse_llm_json(raw_response)
    if not plan.get("run_id"):
        plan["run_id"] = state.run_id
    if not plan.get("original_prompt"):
        plan["original_prompt"] = state.original_prompt

    # Anti-loop guard: identical plan check
    plan_tasks = plan.get("tasks", [])
    current_hash = hashlib.sha256(json.dumps(plan_tasks, sort_keys=True).encode("utf-8")).hexdigest()
    if state.prior_plan_hash == current_hash and state.architect_revisions_used > 0:
        state.status = "aborted"
        state.add_event("anti_loop_detected", "Architect generated identical plan on revision", "3")
        return "aborted"
    state.prior_plan_hash = current_hash

    # Save message
    state.messages["plan"] = plan
    store.save_message(state.run_id, "plan", plan)
    state.add_event(
        "architect_plan_generated",
        f"Generated {len(plan_tasks)} tasks for run {state.run_id}",
        "1",
    )
    return "orchestrator"


def run_orchestrator(state: PipelineState, store: ContextStore, model: str = "winter-prime:latest") -> str:
    """Orchestrator Phase: Constructs DAG, assigns roles/tools (AnnotatedPlanMessage)."""
    if state.orchestrator_revisions_used >= state.orchestrator_budget:
        state.status = "aborted"
        state.add_event("budget_exhausted", "Orchestrator revision budget exhausted", "3")
        return "aborted"

    sys_prompt = load_role_prompt("orchestrator")
    plan = state.messages.get("plan", {})
    user_payload: Dict[str, Any] = {
        "run_id": state.run_id,
        "plan": plan,
        "revision": state.orchestrator_revisions_used,
    }
    if state.orchestrator_revisions_used > 0:
        feedback = state.messages.get("review_verdict") or state.messages.get("security_verdict")
        if feedback:
            user_payload["prior_feedback"] = feedback

    raw_response = stage_chat(
        role="orchestrator",
        system_prompt=sys_prompt,
        user_content=json.dumps(user_payload, indent=2),
        model=model,
    )
    annotated_plan = parse_llm_json(raw_response)
    if not annotated_plan.get("run_id"):
        annotated_plan["run_id"] = state.run_id
    if not annotated_plan.get("original_prompt"):
        annotated_plan["original_prompt"] = state.original_prompt

    # Save message
    state.messages["annotated_plan"] = annotated_plan
    store.save_message(state.run_id, "annotated_plan", annotated_plan)
    dag_nodes = annotated_plan.get("dag", {}).get("nodes", [])
    state.add_event(
        "orchestrator_plan_annotated",
        f"Annotated plan with {len(dag_nodes)} DAG nodes",
        "3",
    )
    return "reviewer"


def run_reviewer(state: PipelineState, store: ContextStore, model: str = "winter-prime:latest") -> str:
    """Reviewer Phase: Deterministic pre-filter + LLM review audit (ReviewVerdict)."""
    annotated_plan = state.messages.get("annotated_plan", {})

    # Step 1: Deterministic Pre-Filter
    pre_filter_verdict = validate_annotated_plan(annotated_plan, state.original_prompt)
    if pre_filter_verdict.get("verdict") != "approved":
        state.messages["review_verdict"] = pre_filter_verdict
        store.save_message(state.run_id, "review_verdict", pre_filter_verdict)
        return_to = pre_filter_verdict.get("return_to", "orchestrator")
        state.add_event(
            "pre_filter_rejected",
            f"Pre-filter rejected plan with {len(pre_filter_verdict.get('violations', []))} violations -> {return_to}",
            "3",
        )
        if return_to == "architect":
            state.architect_revisions_used += 1
            return "architect"
        else:
            state.orchestrator_revisions_used += 1
            return "orchestrator"

    # Step 2: LLM Reviewer Audit
    sys_prompt = load_role_prompt("reviewer")
    raw_response = stage_chat(
        role="reviewer",
        system_prompt=sys_prompt,
        user_content=json.dumps(annotated_plan, indent=2),
        model=model,
    )
    verdict = parse_llm_json(raw_response)
    if not verdict.get("run_id"):
        verdict["run_id"] = state.run_id

    state.messages["review_verdict"] = verdict
    store.save_message(state.run_id, "review_verdict", verdict)

    if verdict.get("verdict") == "approved":
        state.status = "approved"
        state.add_event("reviewer_approved", "Plan passed reviewer audit", "4")
        return "security"
    else:
        return_to = verdict.get("return_to", "orchestrator")
        state.add_event(
            "reviewer_rejected",
            f"Reviewer rejected plan -> {return_to}",
            "4",
        )
        if return_to == "architect":
            state.architect_revisions_used += 1
            return "architect"
        else:
            state.orchestrator_revisions_used += 1
            return "orchestrator"


def run_security(state: PipelineState, store: ContextStore, model: str = "winter-prime:latest") -> str:
    """Security Gate Phase: STRIDE threat modeling (SecurityVerdict)."""
    sys_prompt = load_role_prompt("security")
    annotated_plan = state.messages.get("annotated_plan", {})

    raw_response = stage_chat(
        role="security",
        system_prompt=sys_prompt,
        user_content=json.dumps(annotated_plan, indent=2),
        model=model,
    )
    verdict = parse_llm_json(raw_response)
    if not verdict.get("run_id"):
        verdict["run_id"] = state.run_id

    state.messages["security_verdict"] = verdict
    store.save_message(state.run_id, "security_verdict", verdict)

    if verdict.get("verdict") == "cleared":
        state.status = "security_cleared"
        state.add_event("security_cleared", "STRIDE threat modeling cleared plan", "2")
        return "dispatch"
    else:
        fault_type = verdict.get("fault_type", "assignment")
        return_to = "architect" if fault_type == "scope" else "orchestrator"
        state.add_event(
            "security_rejected",
            f"Security rejected plan with fault_type={fault_type} -> {return_to}",
            "2",
        )
        if return_to == "architect":
            state.architect_revisions_used += 1
            return "architect"
        else:
            state.orchestrator_revisions_used += 1
            return "orchestrator"


def run_dispatch(state: PipelineState, store: ContextStore, model: str = "winter-prime:latest") -> str:
    """Dispatch Phase: Prepares executor tasks, snapshots, and task messages."""
    annotated_plan = state.messages.get("annotated_plan", {})
    tasks = annotated_plan.get("tasks", [])

    for task in tasks:
        tid = task.get("task_id", "unknown")
        role = task.get("assigned_agent", "coder")
        state.tasks[tid] = {
            "status": "pending",
            "retries": 0,
            "role": role,
        }

        # Build ContextSnapshot (§10.4)
        role_sys_prompt = load_role_prompt(role)
        sys_hash = ContextStore.prompt_hash(role_sys_prompt)
        snapshot = {
            "schema_version": "1.0",
            "run_id": state.run_id,
            "task_id": tid,
            "role": role,
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "system_prompt_hash": sys_hash,
            "tool_registry_version": "2.0",
            "rules_registry_version": "2.0",
            "agent_registry_version": "2.0",
            "injected_lesson_ids": [],
            "injected_lesson_count": 0,
            "task_message_ref": f"runs/{state.run_id}/tasks/{tid}/task_message.json",
            "context_token_estimate": 1000,
            "model_used": model,
        }
        store.save_snapshot(state.run_id, tid, snapshot)

        # Build TaskMessage (§3.6)
        task_msg = {
            "schema_version": "2.0",
            "message_type": "task",
            "run_id": state.run_id,
            "task_id": tid,
            "role": role,
            "description": task.get("description", ""),
            "domain_tags": task.get("domain_tags", []),
            "tools_available": [{"name": t, "schema": {}} for t in task.get("tools_required", [])],
            "inputs": {inp: "" for inp in task.get("inputs", [])},
            "constraints": task.get("constraints", []),
            "injected_lessons": [],
            "original_prompt": state.original_prompt,
            "expected_cognition": {
                "analysis": "required",
                "risks": "required",
                "solution": "required",
                "verification": "required",
            },
        }
        store.save_task_message(state.run_id, tid, task_msg)

    state.status = "complete"
    state.add_event(
        "dispatch_initialized",
        f"Initialized dispatch for {len(tasks)} tasks",
        "3",
    )
    return "complete"


PHASE_DISPATCH = {
    "architect": run_architect,
    "orchestrator": run_orchestrator,
    "reviewer": run_reviewer,
    "security": run_security,
    "dispatch": run_dispatch,
}


def run_pipeline(
    prompt: str,
    run_id: Optional[str] = None,
    model: str = "winter-prime:latest",
    store: Optional[ContextStore] = None,
) -> dict:
    """Execute the full Arc-Orc-Rev pipeline loop."""
    if not run_id:
        run_id = uuid.uuid4().hex

    if store is None:
        store = ContextStore()

    state = PipelineState(run_id=run_id, original_prompt=prompt)
    store.save_state(run_id, state.to_dict())

    while state.current_phase not in ("complete", "aborted"):
        phase_fn = PHASE_DISPATCH.get(state.current_phase)
        if not phase_fn:
            state.status = "aborted"
            state.add_event("unknown_phase", f"No handler for phase: {state.current_phase}", "3")
            break

        next_phase = phase_fn(state, store, model=model)
        state.current_phase = next_phase
        store.save_state(run_id, state.to_dict())

    # If run finished, seal to cold storage
    if state.status in ("complete", "aborted"):
        try:
            store.seal_run(run_id)
        except Exception as e:
            state.add_event("seal_failed", f"Failed to seal run: {e}", "3")

    return state.to_dict()


def resume_pipeline(
    run_id: str,
    model: str = "winter-prime:latest",
    store: Optional[ContextStore] = None,
) -> dict:
    """Resume an aborted or in-flight pipeline run from state.json."""
    if store is None:
        store = ContextStore()

    state_dict = store.load(f"runs/{run_id}/state.json")
    state = PipelineState.from_dict(state_dict)

    while state.current_phase not in ("complete", "aborted"):
        phase_fn = PHASE_DISPATCH.get(state.current_phase)
        if not phase_fn:
            state.status = "aborted"
            state.add_event("unknown_phase", f"No handler for phase: {state.current_phase}", "3")
            break

        next_phase = phase_fn(state, store, model=model)
        state.current_phase = next_phase
        store.save_state(run_id, state.to_dict())

    if state.status in ("complete", "aborted"):
        try:
            store.seal_run(run_id)
        except Exception as e:
            state.add_event("seal_failed", f"Failed to seal run: {e}", "3")

    return state.to_dict()


def main():
    parser = argparse.ArgumentParser(description="Arc-Orc-Rev Multi-Agent Pipeline Runner")
    parser.add_argument("prompt", nargs="?", help="User prompt to execute")
    parser.add_argument("--resume", metavar="RUN_ID", help="Resume an aborted run")
    parser.add_argument("--model", default="winter-prime:latest", help="Ollama model to use")
    args = parser.parse_args()

    if args.resume:
        result = resume_pipeline(args.resume, model=args.model)
    elif args.prompt:
        prompt_content = args.prompt
        if os.path.isfile(args.prompt):
            with open(args.prompt, "r", encoding="utf-8") as f:
                prompt_content = f.read().strip()
        result = run_pipeline(prompt_content, model=args.model)
    else:
        parser.error("Provide a prompt or --resume <run_id>")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
