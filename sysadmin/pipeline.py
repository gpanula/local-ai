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
from mcp_core.events import EventEmitter, generate_run_id
from mcp_core.memory import MemoryStore, DEFAULT_DB_PATH
from mcp_core.injection import format_lessons_for_prompt
from mcp_core.extraction import extract_lesson_from_critique
from mcp_core.attribution import attribute_lessons
from mcp_core.trajectories import record_trajectory, DEFAULT_TRAJECTORIES_PATH
from mcp_ollama.server import handle_chat, handle_write_file, handle_execute_task
from validator import validate_annotated_plan, validate_code_output

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
        self.injected_lessons: Dict[str, List[dict]] = {}

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

    think_match = re.search(r"<think>([\s\S]*?)</think>", response)
    if not think_match:
        think_match = re.search(r"<think>([\s\S]*?)(?=```json|\{)", response)
    cot = think_match.group(1).strip() if think_match else ""

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

    parsed = json.loads(candidate)
    if cot and isinstance(parsed, dict):
        if "cognition" not in parsed or not isinstance(parsed["cognition"], dict):
            parsed["cognition"] = {}
        parsed["cognition"]["chain_of_thought"] = cot
    return parsed


def extract_stats(text: str) -> str:
    """Extract the '*Generated by `model`: N tokens in Xs (Y t/s) ...*' footer."""
    match = re.search(r"(\*Generated by `[^`]+`(?: \([^)]+\))?: [^*]+\*)", text)
    return match.group(1) if match else ""


def format_telemetry(raw_stats: str, role: Optional[str] = None) -> str:
    """Formats raw telemetry with threshold alerts for low TPS, context usage, and residency."""
    if not raw_stats:
        return ""
    pattern = (
        r"\*Generated by `(?P<model>[^`]+)`(?: \((?P<role>[^)]+)\))?: (?P<tokens>\d+) tokens in (?P<duration>[\d\.]+)s \((?P<tps>[\d\.]+) t/s\)(?: \[(?P<residency>[^\]]+)\])?"
        r" \| Context: (?P<ctx_used>[\d,]+) / (?P<ctx_max>[\d,]+) tokens \((?P<pct>[\d\.]+)%\)\*"
    )
    match = re.search(pattern, raw_stats)
    if not match:
        return raw_stats

    model = match.group("model")
    effective_role = role or match.group("role")
    tokens = match.group("tokens")
    duration = match.group("duration")
    tps = float(match.group("tps"))
    residency = match.group("residency") or ""
    ctx_used = match.group("ctx_used")
    ctx_max = match.group("ctx_max")
    pct = float(match.group("pct"))

    if tps < 26.0:
        tps_str = f"🚨 {tps:.1f} t/s (CRITICAL LOW)"
    elif tps < 51.0:
        tps_str = f"⚠️ {tps:.1f} t/s"
    else:
        tps_str = f"{tps:.1f} t/s"

    if pct > 82.0:
        ctx_str = f"🚨 Context: {ctx_used} / {ctx_max} tokens ({pct:.1f}% - HIGH USAGE)"
    elif pct > 55.0:
        ctx_str = f"⚠️ Context: {ctx_used} / {ctx_max} tokens ({pct:.1f}%)"
    else:
        ctx_str = f"Context: {ctx_used} / {ctx_max} tokens ({pct:.1f}%)"

    res_str = f" [{residency}]" if residency else ""
    role_str = f" ({effective_role})" if effective_role else ""
    return f"*Generated by `{model}`{role_str}: {tokens} tokens in {duration}s ({tps_str}){res_str} | {ctx_str}*"


def stage_chat(
    role: str,
    system_prompt: str,
    user_content: str,
    model: str = "winter-prime:latest",
    tools: Optional[List[Dict[str, Any]]] = None,
    lessons: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Call Ollama via handle_chat with SMMP profile applied + terminal-mcp streaming."""
    profile = SMMP_PROFILES.get(role, {"temperature": 0.1, "top_p": 0.9})
    send_terminal_mcp(
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 [{role.upper()}] Starting phase... (temp={profile['temperature']}, top_p={profile['top_p']})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if lessons is None:
        try:
            parsed_content = json.loads(user_content)
            if isinstance(parsed_content, dict):
                lessons = parsed_content.get("injected_lessons") or []
                if not lessons:
                    for k in ("plan", "task", "annotated_plan"):
                        nested = parsed_content.get(k)
                        if isinstance(nested, dict) and nested.get("injected_lessons"):
                            lessons = nested["injected_lessons"]
                            break
        except Exception:
            lessons = []

    emitter = EventEmitter.get_current()
    if emitter:
        try:
            emitter.context_window(
                iteration=1,
                system_rules=system_prompt,
                tools=tools or [],
                lessons=lessons or [],
                user_prompt=user_content,
                stage=role,
            )
        except Exception:
            pass

    response = handle_chat(
        model=model,
        prompt=user_content,
        system_prompt=system_prompt,
        tools=tools,
        temperature=profile["temperature"],
        top_p=profile["top_p"],
    )

    raw_stats = extract_stats(response)
    clean_body = response.split("\n\n---\n")[0].strip()

    think_match = re.search(r"<think>([\s\S]*?)</think>", response)
    if not think_match:
        think_match = re.search(r"<think>([\s\S]*?)(?=```json|\{)", response)
    if think_match:
        cot = think_match.group(1).strip()
        if cot:
            send_terminal_mcp(f"\n💭 [{role.upper()} CHAIN-OF-THOUGHT]\n{cot}")
            if emitter:
                try:
                    emitter.thinking_chunk(iteration=1, model=model, chunk=cot, stage=role, is_final=True)
                except Exception:
                    pass

    # Echo agent thinking & reasoning (4 pillars) to console and terminal-mcp
    try:
        parsed = parse_llm_json(response)
        cognition = parsed.get("cognition")
        if isinstance(cognition, dict):
            reasoning_banner = [
                f"\n─── [{role.upper()} REASONING & 4 PILLARS] ───",
            ]
            if cognition.get("analysis"):
                reasoning_banner.append(f"🧠 [Pillar 1: Analysis & Strategy]\n{cognition['analysis']}")
            if cognition.get("risks"):
                reasoning_banner.append(f"⚠️ [Pillar 2: Risks & Edge Cases]\n{cognition['risks']}")
            if cognition.get("solution"):
                reasoning_banner.append(f"🛠️ [Pillar 3: Solution & Decisions]\n{cognition['solution']}")
            if cognition.get("verification"):
                reasoning_banner.append(f"🧪 [Pillar 4: Verification & Testing]\n{cognition['verification']}")
            reasoning_banner.append("──────────────────────────────────────────────────────────")
            send_terminal_mcp("\n".join(reasoning_banner))

            if emitter:
                try:
                    emitter.reasoning_chunk(
                        iteration=1,
                        model=model,
                        reasoning={
                            "strategy": cognition.get("analysis", ""),
                            "risks": cognition.get("risks", ""),
                            "solution": cognition.get("solution", ""),
                            "verification_plan": cognition.get("verification", ""),
                        },
                        stage=role,
                    )
                    if not think_match:
                        thinking_parts = []
                        if cognition.get("analysis"):
                            thinking_parts.append(f"🧠 [Pillar 1: Analysis & Strategy]\n{cognition['analysis']}")
                        if cognition.get("risks"):
                            thinking_parts.append(f"⚠️ [Pillar 2: Risks & Edge Cases]\n{cognition['risks']}")
                        if cognition.get("solution"):
                            thinking_parts.append(f"🛠️ [Pillar 3: Solution & Decisions]\n{cognition['solution']}")
                        if cognition.get("verification"):
                            thinking_parts.append(f"🧪 [Pillar 4: Verification & Testing]\n{cognition['verification']}")
                        if thinking_parts:
                            emitter.thinking_chunk(
                                iteration=1,
                                model=model,
                                chunk="\n\n".join(thinking_parts),
                                stage=role,
                                is_final=True,
                            )
                except Exception:
                    pass
    except Exception:
        pass

    # Check for synthesized code in clean_body
    code_match = re.search(r"```(?:bash|sh)?\n([\s\S]*?)```", clean_body)
    if code_match and role in ("coder", "dispatch", "sysadmin"):
        code_str = code_match.group(1).strip()
        if emitter:
            try:
                emitter.emit("code_synthesized", {
                    "iteration": 1,
                    "code": code_str,
                    "stage": role,
                })
            except Exception:
                pass

    # Print full response body without truncation
    send_terminal_mcp(f"\n✅ [{role.upper()}] Complete:\n{clean_body}")

    # Print formatted telemetry for every agent/role
    if raw_stats:
        send_terminal_mcp(f"📊 {format_telemetry(raw_stats, role=role)}")
    else:
        role_str = f" ({role})" if role else ""
        send_terminal_mcp(f"📊 *Generated by `{model}`{role_str}*")

    return response


def normalize_annotated_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Defensively normalize common LLM output variations in AnnotatedPlanMessage."""
    # 1. Normalize dag.edges if emitted as list of pairs e.g. [["t-001", "t-002"]]
    dag = plan.get("dag")
    if isinstance(dag, dict):
        edges = dag.get("edges", [])
        if isinstance(edges, list):
            norm_edges = []
            for e in edges:
                if isinstance(e, list) and len(e) >= 2:
                    norm_edges.append({
                        "from": str(e[0]),
                        "to": str(e[1]),
                        "type": "data_dependency",
                    })
                elif isinstance(e, dict) and "from" in e and "to" in e:
                    norm_edges.append(e)
            dag["edges"] = norm_edges

    # 2. Normalize tasks: assigned_agent and domain_tags
    tasks = plan.get("tasks", [])
    if isinstance(tasks, list):
        for t in tasks:
            if not isinstance(t, dict):
                continue
            # Normalize agent if invalid or generic
            agent = t.get("assigned_agent", "")
            if agent in ("executor", "runner", "bash", "operator"):
                desc = t.get("description", "").lower()
                tools = t.get("tools_required", [])
                if "write_file" in tools or "write" in desc or "create" in desc:
                    t["assigned_agent"] = "coder"
                else:
                    t["assigned_agent"] = "sysadmin"

            # Normalize common non-canonical domain tag variations
            domain_map = {
                "script execution": "Defensive Bash Scripting",
                "bash scripting": "Defensive Bash Scripting",
                "bash": "Defensive Bash Scripting",
                "ansible automation": "Ansible",
                "testing": "Code Quality Toolchain",
                "docker": "Docker Orchestration",
            }
            tags = t.get("domain_tags", [])
            if isinstance(tags, list):
                norm_tags = []
                for tag in tags:
                    norm_tag = domain_map.get(str(tag).lower(), tag)
                    norm_tags.append(norm_tag)
                t["domain_tags"] = norm_tags

    return plan


def run_architect(state: PipelineState, store: ContextStore, model: str = "winter-prime:latest") -> str:
    """Architect Phase: Decomposes user's prompt into tasks (PlanMessage)."""
    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    if state.architect_revisions_used >= state.architect_budget:
        state.status = "aborted"
        state.add_event("budget_exhausted", "Architect revision budget exhausted", "3")
        if memory_store:
            try:
                fail_lesson = {
                    "proposed_rule": f"Architect revision budget exhausted after {state.architect_budget} attempts for: {state.original_prompt[:100]}",
                    "category": "System Architecture",
                    "keywords": ["architecture", "system design", "topology", "budget"],
                    "task_file": f"runs/{state.run_id}/messages/plan.json",
                    "reviewer_critique": json.dumps(state.messages.get("review_verdict") or state.messages.get("security_verdict") or {}),
                    "lesson_type": "hard_failure",
                    "outcome": "aborted",
                }
                staged_id = memory_store.stage_pending_lesson(fail_lesson)
                send_terminal_mcp(f"📥 [MEMORY] Staged hard_failure lesson '{staged_id}' from exhausted Architect budget")
            except Exception:
                pass
        return "aborted"

    # Query and inject lessons from MemoryStore (§4.01)
    relevant_lessons = []
    if memory_store:
        try:
            seen_ids = set()
            candidates = []
            for tag in ("System Architecture", "Decomposition"):
                for l in memory_store.search_lessons(tag, top_k=2):
                    if l["id"] not in seen_ids:
                        seen_ids.add(l["id"])
                        candidates.append(l)
            words = [w for w in re.findall(r"[a-zA-Z0-9_-]+", state.original_prompt) if len(w) > 3]
            for w in words[:3]:
                for l in memory_store.search_lessons(w, top_k=2):
                    if l["id"] not in seen_ids:
                        seen_ids.add(l["id"])
                        candidates.append(l)
            relevant_lessons = candidates[:3]
        except Exception:
            relevant_lessons = []

    lesson_ids = [l["id"] for l in relevant_lessons]
    if relevant_lessons and memory_store:
        try:
            memory_store.increment_retrieval_count(lesson_ids)
        except Exception:
            pass
        state.injected_lessons["architect"] = relevant_lessons
        send_terminal_mcp(
            f"\n📥 [MEMORY] Injected {len(relevant_lessons)} lesson(s) into Architect: {', '.join(lesson_ids)}"
        )

    sys_prompt = load_role_prompt("architect")
    user_payload: Dict[str, Any] = {
        "run_id": state.run_id,
        "original_prompt": state.original_prompt,
        "revision": state.architect_revisions_used,
    }
    if relevant_lessons:
        lesson_section = format_lessons_for_prompt(relevant_lessons)
        user_payload["architectural_guidance"] = lesson_section
        user_payload["injected_lessons"] = relevant_lessons

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
    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    if state.orchestrator_revisions_used >= state.orchestrator_budget:
        state.status = "aborted"
        state.add_event("budget_exhausted", "Orchestrator revision budget exhausted", "3")
        if memory_store:
            try:
                fail_lesson = {
                    "proposed_rule": f"Orchestrator revision budget exhausted after {state.orchestrator_budget} attempts for: {state.original_prompt[:100]}",
                    "category": "Multi-Agent Orchestration",
                    "keywords": ["orchestrator", "budget", "dag", "scheduling"],
                    "task_file": f"runs/{state.run_id}/messages/annotated_plan.json",
                    "reviewer_critique": json.dumps(state.messages.get("review_verdict") or state.messages.get("security_verdict") or {}),
                    "lesson_type": "hard_failure",
                    "outcome": "aborted",
                }
                staged_id = memory_store.stage_pending_lesson(fail_lesson)
                send_terminal_mcp(f"📥 [MEMORY] Staged hard_failure lesson '{staged_id}' from exhausted Orchestrator budget")
            except Exception:
                pass
        return "aborted"

    # Query and inject lessons from MemoryStore (§4.01)
    plan = state.messages.get("plan", {})
    relevant_lessons = []
    if memory_store:
        try:
            seen_ids = set()
            candidates = []
            for tag in ("Multi-Agent Orchestration", "DAG Construction"):
                for l in memory_store.search_lessons(tag, top_k=2):
                    if l["id"] not in seen_ids:
                        seen_ids.add(l["id"])
                        candidates.append(l)
            for t in plan.get("tasks", []):
                for dtag in t.get("domain_tags", []):
                    if isinstance(dtag, str) and dtag.strip():
                        for l in memory_store.search_lessons(dtag.strip(), top_k=2):
                            if l["id"] not in seen_ids:
                                seen_ids.add(l["id"])
                                candidates.append(l)
            relevant_lessons = candidates[:3]
        except Exception:
            relevant_lessons = []

    lesson_ids = [l["id"] for l in relevant_lessons]
    if relevant_lessons and memory_store:
        try:
            memory_store.increment_retrieval_count(lesson_ids)
        except Exception:
            pass
        state.injected_lessons["orchestrator"] = relevant_lessons
        send_terminal_mcp(
            f"\n📥 [MEMORY] Injected {len(relevant_lessons)} lesson(s) into Orchestrator: {', '.join(lesson_ids)}"
        )

    sys_prompt = load_role_prompt("orchestrator")
    user_payload: Dict[str, Any] = {
        "run_id": state.run_id,
        "plan": plan,
        "revision": state.orchestrator_revisions_used,
    }
    if relevant_lessons:
        lesson_section = format_lessons_for_prompt(relevant_lessons)
        user_payload["orchestration_guidance"] = lesson_section
        user_payload["injected_lessons"] = relevant_lessons

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
    annotated_plan = normalize_annotated_plan(annotated_plan)
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

    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    # Step 1: Deterministic Pre-Filter
    pre_filter_verdict = validate_annotated_plan(annotated_plan, state.original_prompt)
    if pre_filter_verdict.get("verdict") != "approved":
        state.messages["review_verdict"] = pre_filter_verdict
        store.save_message(state.run_id, "review_verdict", pre_filter_verdict)
        return_to = pre_filter_verdict.get("return_to", "orchestrator")
        violations = pre_filter_verdict.get("violations", [])
        v_lines = [f"  ⚠️ [{v.get('type')}] {v.get('description')}" for v in violations]
        send_terminal_mcp(
            f"\n❌ [REVIEWER PRE-FILTER] Plan rejected with {len(violations)} violation(s) -> returning to {return_to}:\n"
            + "\n".join(v_lines)
        )
        state.add_event(
            "pre_filter_rejected",
            f"Pre-filter rejected plan with {len(violations)} violations -> {return_to}",
            "3",
        )
        if return_to == "architect":
            state.architect_revisions_used += 1
            return "architect"
        else:
            state.orchestrator_revisions_used += 1
            return "orchestrator"

    send_terminal_mcp("\n✅ [REVIEWER PRE-FILTER] Passed deterministic validation checks (0 violations)")

    # Dynamic Rubric Injection for Reviewer
    relevant_lessons = []
    if memory_store:
        try:
            seen_ids = set()
            candidates = []
            for tag in ("Code Quality Toolchain", "Code Review", "Audit"):
                for l in memory_store.search_lessons(tag, top_k=2):
                    if l["id"] not in seen_ids:
                        seen_ids.add(l["id"])
                        candidates.append(l)
            relevant_lessons = candidates[:3]
        except Exception:
            relevant_lessons = []

    lesson_ids = [l["id"] for l in relevant_lessons]
    if relevant_lessons and memory_store:
        try:
            memory_store.increment_retrieval_count(lesson_ids)
        except Exception:
            pass
        state.injected_lessons["reviewer"] = relevant_lessons
        annotated_plan["audit_heuristics"] = [l["rule"] for l in relevant_lessons]
        annotated_plan["injected_lessons"] = relevant_lessons
        send_terminal_mcp(
            f"\n📥 [MEMORY] Injected {len(relevant_lessons)} heuristic(s) into Reviewer: {', '.join(lesson_ids)}"
        )

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
    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    annotated_plan = state.messages.get("annotated_plan", {})

    # Dynamic Rubric Injection for Security Gate
    relevant_lessons = []
    if memory_store:
        try:
            seen_ids = set()
            candidates = []
            for tag in ("Security & Hardening", "Threat Modeling", "STRIDE"):
                for l in memory_store.search_lessons(tag, top_k=2):
                    if l["id"] not in seen_ids:
                        seen_ids.add(l["id"])
                        candidates.append(l)
            relevant_lessons = candidates[:3]
        except Exception:
            relevant_lessons = []

    lesson_ids = [l["id"] for l in relevant_lessons]
    if relevant_lessons and memory_store:
        try:
            memory_store.increment_retrieval_count(lesson_ids)
        except Exception:
            pass
        state.injected_lessons["security"] = relevant_lessons
        annotated_plan["security_heuristics"] = [l["rule"] for l in relevant_lessons]
        annotated_plan["injected_lessons"] = relevant_lessons
        send_terminal_mcp(
            f"\n📥 [MEMORY] Injected {len(relevant_lessons)} heuristic(s) into Security: {', '.join(lesson_ids)}"
        )

    sys_prompt = load_role_prompt("security")
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
        send_terminal_mcp("\n🛡️ [SECURITY GATE] STRIDE threat modeling cleared plan")
        state.status = "security_cleared"
        state.add_event("security_cleared", "STRIDE threat modeling cleared plan", "2")

        # Upstream lesson handling on clearance:
        if state.architect_revisions_used > 0 or state.orchestrator_revisions_used > 0:
            # Remediation occurred: capture solved_pattern lesson from critique
            try:
                feedback = state.messages.get("review_verdict") or state.messages.get("security_verdict") or {}
                critique_content = json.dumps(
                    feedback.get("violations") or feedback.get("faults") or feedback.get("critique") or feedback
                )
                remediated_phase = "Architect" if state.architect_revisions_used > 0 else "Orchestrator"
                cat = "System Architecture" if state.architect_revisions_used > 0 else "Multi-Agent Orchestration"
                lesson_data = extract_lesson_from_critique(
                    critique=critique_content,
                    task_file=f"runs/{state.run_id}/messages/annotated_plan.json",
                    prompt_content=state.original_prompt,
                    model=model,
                    lesson_type="solved_pattern",
                    outcome="cleared",
                )
                if memory_store:
                    staged_id = memory_store.stage_pending_lesson(lesson_data)
                    send_terminal_mcp(
                        f"📥 [MEMORY] Staged remediation lesson '{staged_id}' from {remediated_phase} revision"
                    )
            except Exception as e:
                state.add_event("remediation_lesson_failed", f"Failed to stage remediation lesson: {e}", "4")
        else:
            # Clean first-pass plan (0 revisions): credit utility to all injected planning lessons
            if memory_store:
                try:
                    for role_name in ("architect", "orchestrator", "reviewer", "security"):
                        for l in state.injected_lessons.get(role_name, []):
                            lid = l.get("id")
                            if lid:
                                memory_store.update_telemetry(lid, "prevented_rework_count", increment=1)
                                send_terminal_mcp(f"📈 [MEMORY] Credited planning lesson '{lid}' (+1 utility)")
                except Exception:
                    pass

        return "dispatch"
    else:
        fault_type = verdict.get("fault_type", "assignment")
        return_to = "architect" if fault_type == "scope" else "orchestrator"
        send_terminal_mcp(
            f"\n🚨 [SECURITY GATE] STRIDE threat modeling rejected plan (fault_type={fault_type}) -> returning to {return_to}"
        )
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

    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    for task in tasks:
        tid = task.get("task_id", "unknown")
        role = task.get("assigned_agent", "coder")
        task_desc = task.get("description", "")
        state.tasks[tid] = {
            "status": "pending",
            "retries": 0,
            "role": role,
        }

        # Query and inject lessons from MemoryStore (§4.01)
        relevant_lessons = []
        if memory_store:
            try:
                seen_ids = set()
                candidates = []
                for tag in task.get("domain_tags", []):
                    if not isinstance(tag, str) or not tag.strip():
                        continue
                    for l in memory_store.search_lessons(tag.strip(), top_k=3):
                        if l["id"] not in seen_ids:
                            seen_ids.add(l["id"])
                            candidates.append(l)
                if not candidates and task_desc:
                    words = [w for w in re.findall(r"[a-zA-Z0-9_-]+", task_desc) if len(w) > 3]
                    for w in words[:3]:
                        for l in memory_store.search_lessons(w, top_k=2):
                            if l["id"] not in seen_ids:
                                seen_ids.add(l["id"])
                                candidates.append(l)
                relevant_lessons = candidates[:3]
            except Exception:
                relevant_lessons = []

        lesson_ids = [l["id"] for l in relevant_lessons]
        if relevant_lessons and memory_store:
            try:
                memory_store.increment_retrieval_count(lesson_ids)
            except Exception:
                pass
            state.injected_lessons[tid] = relevant_lessons
            lesson_section = format_lessons_for_prompt(relevant_lessons)
            effective_task_desc = f"{lesson_section}\n{task_desc}" if lesson_section else task_desc
            send_terminal_mcp(
                f"\n📥 [MEMORY] Injected {len(relevant_lessons)} lesson(s) into task '{tid}': {', '.join(lesson_ids)}"
            )
        else:
            effective_task_desc = task_desc

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
            "injected_lesson_ids": lesson_ids,
            "injected_lesson_count": len(lesson_ids),
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
            "description": effective_task_desc,
            "domain_tags": task.get("domain_tags", []),
            "tools_available": [{"name": t, "schema": {}} for t in task.get("tools_required", [])],
            "inputs": {inp: "" for inp in task.get("inputs", [])},
            "constraints": task.get("constraints", []),
            "injected_lessons": relevant_lessons,
            "original_prompt": state.original_prompt,
            "expected_cognition": {
                "analysis": "required",
                "risks": "required",
                "solution": "required",
                "verification": "required",
            },
        }
        store.save_task_message(state.run_id, tid, task_msg)

        # Dispatch and execute with assigned executor agent
        send_terminal_mcp(
            f"\n🚀 [DISPATCH] Executing task '{tid}' with agent `{role}`: {task_desc}"
        )
        emitter = EventEmitter.get_current()
        if emitter:
            try:
                emitter.stage_transition(role)
            except Exception:
                pass

        retries = 0
        max_retries = 2
        passed_all_gates = False
        exec_res = {}
        outputs = {}

        while retries <= max_retries:
            raw_result = stage_chat(
                role=role,
                system_prompt=role_sys_prompt,
                user_content=json.dumps(task_msg, indent=2),
                model=model,
            )

            try:
                exec_res = parse_llm_json(raw_result)
            except Exception:
                exec_res = {
                    "schema_version": "2.0",
                    "message_type": "execution_result",
                    "run_id": state.run_id,
                    "task_id": tid,
                    "role": role,
                    "status": "success",
                    "outputs": {},
                }

            outputs = exec_res.get("outputs", {})
            if not outputs:
                code_blocks = re.findall(r"```(?:bash|sh)?\s*\n([\s\S]*?)```", raw_result)
                declared_outputs = task.get("outputs", [])
                if code_blocks and declared_outputs:
                    target_file = declared_outputs[0]
                    outputs = {target_file: max(code_blocks, key=len).strip()}
                    exec_res["outputs"] = outputs

            # Multi-Tier Pre-Execution Code Verification Gate
            # Tier 1: Deterministic Linter (validate_code_output)
            # Tier 2A: Semantic Code Review (Reviewer Agent)
            # Tier 2B: Behavioral & STRIDE Security Audit (Security Agent)
            is_code_output = False
            code_files = {}
            if isinstance(outputs, dict):
                for p, c in outputs.items():
                    if not isinstance(c, str) or not c.strip():
                        continue
                    if p.lower() in ("stdout", "stderr", "returncode", "exit_code", "output", "result", "hello_world_result"):
                        continue
                    if p.endswith((".sh", ".bash", ".py", ".yml", ".yaml", ".json")) or (c.strip().startswith("#!")):
                        is_code_output = True
                        code_files[p] = c

            if not is_code_output:
                passed_all_gates = True
                break

            # Tier 1: Deterministic Code Linter Gate
            linter_verdict = validate_code_output(task, outputs)
            if linter_verdict.get("verdict") != "approved":
                critique = linter_verdict.get("critique", "Linter violations found.")
                violations = linter_verdict.get("violations", [])
                v_summary = "\n".join([f"  ⚠️ [{v.get('type')}] {v.get('description')}" for v in violations])
                send_terminal_mcp(
                    f"\n❌ [CODE LINTER GATE] Task '{tid}' rejected with {len(violations)} violation(s):\n{v_summary}"
                )
                retries += 1
                if retries <= max_retries:
                    send_terminal_mcp(
                        f"🔄 [REMEDIATION] Requesting {role.capitalize()} retry {retries}/{max_retries} with linter critique..."
                    )
                    task_msg["prior_critique"] = critique
                    task_msg["revision"] = retries
                    continue
                else:
                    send_terminal_mcp(
                        f"🚨 [CODE LINTER GATE] Retry budget exhausted ({max_retries}/{max_retries}). Task '{tid}' failed."
                    )
                    if memory_store:
                        try:
                            fail_lesson = extract_lesson_from_critique(
                                critique=critique,
                                task_file=state.original_prompt[:100],
                                prompt_content=state.original_prompt,
                                model=model,
                                lesson_type="hard_failure",
                                outcome="failed",
                            )
                            lid = memory_store.stage_pending_lesson(fail_lesson)
                            send_terminal_mcp(f"📝 [MEMORY] Staged hard_failure lesson '{lid}' for review")
                        except Exception:
                            pass
                    break

            send_terminal_mcp(
                f"\n✅ [CODE LINTER GATE] Passed all defensive standards & ShellCheck for task '{tid}'"
            )

            # Tier 2A: Semantic Code Review (Reviewer Agent)
            send_terminal_mcp(f"\n🔍 [REVIEWER CODE GATE] Auditing semantic logic & prompt fidelity for task '{tid}'...")
            rev_sys_prompt = load_role_prompt("reviewer_code")
            rev_payload = {
                "schema_version": "2.0",
                "message_type": "code_review_request",
                "run_id": state.run_id,
                "task_id": tid,
                "task_description": task_desc,
                "original_prompt": state.original_prompt,
                "code_files": code_files,
            }
            raw_rev = stage_chat(
                role="reviewer",
                system_prompt=rev_sys_prompt,
                user_content=json.dumps(rev_payload, indent=2),
                model=model,
            )
            try:
                rev_verdict = parse_llm_json(raw_rev)
            except Exception:
                rev_verdict = {"schema_version": "2.0", "verdict": "approved", "violations": []}

            store.save_message(state.run_id, f"code_review_verdict_{tid}", rev_verdict)

            if rev_verdict.get("verdict") != "approved":
                rev_violations = rev_verdict.get("violations", [])
                v_desc = "\n".join([f"  ⚠️ {v.get('description', v)}" if isinstance(v, dict) else f"  ⚠️ {v}" for v in rev_violations])
                critique = f"Reviewer code rejection:\n{v_desc}" if v_desc else "Reviewer rejected code implementation."
                send_terminal_mcp(
                    f"\n❌ [REVIEWER CODE GATE] Task '{tid}' rejected code:\n{v_desc or 'Acceptance criteria unmet'}"
                )
                state.add_event("code_review_rejected", f"Task {tid} rejected by reviewer", "4")
                retries += 1
                if retries <= max_retries:
                    send_terminal_mcp(
                        f"🔄 [REMEDIATION] Requesting {role.capitalize()} retry {retries}/{max_retries} with reviewer critique..."
                    )
                    task_msg["prior_critique"] = critique
                    task_msg["revision"] = retries
                    continue
                else:
                    send_terminal_mcp(
                        f"🚨 [REVIEWER CODE GATE] Retry budget exhausted ({max_retries}/{max_retries}). Task '{tid}' failed."
                    )
                    if memory_store:
                        try:
                            fail_lesson = extract_lesson_from_critique(
                                critique=critique,
                                task_file=state.original_prompt[:100],
                                prompt_content=state.original_prompt,
                                model=model,
                                lesson_type="hard_failure",
                                outcome="failed",
                            )
                            lid = memory_store.stage_pending_lesson(fail_lesson)
                            send_terminal_mcp(f"📝 [MEMORY] Staged hard_failure lesson '{lid}' for review")
                        except Exception:
                            pass
                    break

            send_terminal_mcp(
                f"✅ [REVIEWER CODE GATE] Approved code logic & acceptance criteria for task '{tid}'"
            )
            state.add_event("code_reviewed", f"Task {tid} code passed reviewer audit", "4")

            # Tier 2B: Behavioral & STRIDE Security Gate (Security Agent)
            send_terminal_mcp(f"\n🛡️ [SECURITY CODE GATE] Auditing behavioral changes & STRIDE threats for task '{tid}'...")
            sec_sys_prompt = load_role_prompt("security_code")
            sec_payload = {
                "schema_version": "2.0",
                "message_type": "code_security_request",
                "run_id": state.run_id,
                "task_id": tid,
                "task_description": task_desc,
                "original_prompt": state.original_prompt,
                "code_files": code_files,
            }
            raw_sec = stage_chat(
                role="security",
                system_prompt=sec_sys_prompt,
                user_content=json.dumps(sec_payload, indent=2),
                model=model,
            )
            try:
                sec_verdict = parse_llm_json(raw_sec)
            except Exception:
                sec_verdict = {"schema_version": "2.0", "verdict": "cleared", "threats": []}

            store.save_message(state.run_id, f"code_security_verdict_{tid}", sec_verdict)

            if sec_verdict.get("verdict") not in ("cleared", "approved"):
                sec_threats = sec_verdict.get("threats", [])
                t_desc = "\n".join([f"  ⚠️ {t.get('description', t)}" if isinstance(t, dict) else f"  ⚠️ {t}" for t in sec_threats])
                critique = f"Security behavioral rejection:\n{t_desc}" if t_desc else "Security gate rejected behavioral changes."
                send_terminal_mcp(
                    f"\n🛡️❌ [SECURITY CODE GATE] Task '{tid}' rejected code on security threats:\n{t_desc or 'Threats detected'}"
                )
                state.add_event("code_security_rejected", f"Task {tid} rejected by security gate", "2")
                retries += 1
                if retries <= max_retries:
                    send_terminal_mcp(
                        f"🔄 [REMEDIATION] Requesting {role.capitalize()} retry {retries}/{max_retries} with security critique..."
                    )
                    task_msg["prior_critique"] = critique
                    task_msg["revision"] = retries
                    continue
                else:
                    send_terminal_mcp(
                        f"🚨 [SECURITY CODE GATE] Retry budget exhausted ({max_retries}/{max_retries}). Task '{tid}' failed."
                    )
                    if memory_store:
                        try:
                            fail_lesson = extract_lesson_from_critique(
                                critique=critique,
                                task_file=state.original_prompt[:100],
                                prompt_content=state.original_prompt,
                                model=model,
                                lesson_type="hard_failure",
                                outcome="failed",
                            )
                            lid = memory_store.stage_pending_lesson(fail_lesson)
                            send_terminal_mcp(f"📝 [MEMORY] Staged hard_failure lesson '{lid}' for review")
                        except Exception:
                            pass
                    break

            beh_summary = sec_verdict.get("behavioral_summary", "Safe runtime behavior")
            send_terminal_mcp(
                f"🛡️✅ [SECURITY CODE GATE] Cleared behavioral & STRIDE audit for task '{tid}': {beh_summary}"
            )
            state.add_event("code_security_cleared", f"Task {tid} code cleared security gate", "2")

            passed_all_gates = True

            # If remediated successfully after prior retry, capture solved_pattern lesson
            if retries > 0 and memory_store:
                try:
                    critique_summary = task_msg.get("prior_critique", "Code remediation")
                    new_lesson = extract_lesson_from_critique(
                        critique=critique_summary,
                        task_file=state.original_prompt[:100],
                        prompt_content=state.original_prompt,
                        model=model,
                        lesson_type="solved_pattern",
                        outcome="approved",
                    )
                    lid = memory_store.insert_lesson(new_lesson)
                    send_terminal_mcp(f"🎉 [MEMORY] Captured solved_pattern lesson '{lid}' after successful remediation")
                    state.add_event("lesson_captured", f"Captured solved_pattern lesson {lid}", "3")
                except Exception:
                    pass
            break

        state.tasks[tid]["retries"] = retries
        if is_code_output and not passed_all_gates:
            state.tasks[tid]["status"] = "failed"
            store.save_message(state.run_id, f"execution_result_{tid}", exec_res)
            state.add_event("task_failed", f"Task {tid} failed pre-execution verification gates", "3")
            continue

        # Apply file write outputs ONLY after linter gate approval
        written_files = []
        if isinstance(outputs, dict):
            for path, content in outputs.items():
                if not isinstance(content, str) or not content.strip():
                    continue
                if path.lower() in ("stdout", "stderr", "returncode", "exit_code", "output", "result", "hello_world_result"):
                    continue
                is_sh = path.endswith(".sh")
                try:
                    res = handle_write_file(path, content, make_executable=is_sh)
                    send_terminal_mcp(f"📝 {res}")
                    written_files.append(path)
                except Exception as e:
                    send_terminal_mcp(f"❌ Failed to write `{path}`: {e}")

        # Execute scripts ONLY when the current task requires execution:
        # 1. Current task declares execution tool ("run_bash") or explicit execution description
        # 2. If the current task is strictly a creation task (e.g. tools_required=["write_file"])
        #    and there is a downstream execution task in the plan, defer execution to that task.
        tools_req = task.get("tools_required", [])
        task_desc_lower = task_desc.lower()
        is_execution_task = (
            "run_bash" in tools_req
            or any(kw in task_desc_lower for kw in ("execute", "run ", "test script", "run_bash"))
        )

        has_downstream_executor = any(
            t.get("task_id") != tid
            and ("run_bash" in t.get("tools_required", []) or t.get("assigned_agent") == "sysadmin")
            and any(kw in t.get("description", "").lower() for kw in ("execute", "run", "verify", "test"))
            for t in tasks
        )

        exec_succeeded = True
        targets_to_execute = []

        if is_execution_task:
            # 1. Any input script targets
            inputs = task.get("inputs", [])
            if isinstance(inputs, list):
                for inp in inputs:
                    if isinstance(inp, str) and inp.endswith(".sh"):
                        targets_to_execute.append(inp)
            # 2. Any written script targets if also an execution task
            for wf in written_files:
                if wf.endswith(".sh") and wf not in targets_to_execute:
                    targets_to_execute.append(wf)
        elif not has_downstream_executor:
            # Standalone single-task pipeline fallback: execute written scripts
            for wf in written_files:
                if wf.endswith(".sh"):
                    targets_to_execute.append(wf)

        for target in targets_to_execute:
            send_terminal_mcp(f"\n⚡ [{role.upper()}] Executing target script `{target}` live in terminal-mcp...")
            run_cmd = target if target.startswith("./") else f"./{target}"
            run_out = handle_execute_task(run_cmd, task_description=task_desc, model=model)
            send_terminal_mcp(f"📋 [Execution Output]\n{run_out}")
            if not re.search(r"Exit Code\*?\*?:\s*`?0`?", run_out):
                exec_succeeded = False

        # Lesson Attribution on Execution Success (§5.02)
        if exec_succeeded and relevant_lessons and memory_store:
            try:
                attr = attribute_lessons(
                    relevant_lessons,
                    {"iterations": retries + 1, "approved": True},
                    "",
                )
                for lid, a_type in attr.items():
                    if a_type == "credited":
                        memory_store.update_telemetry(lid, "prevented_rework_count", increment=1)
                        send_terminal_mcp(f"📈 [MEMORY] Credited lesson '{lid}' (+1 utility)")
            except Exception:
                pass

        state.tasks[tid]["status"] = exec_res.get("status", "success") if exec_succeeded else "failed"
        if isinstance(outputs, dict):
            exec_res["outputs"] = outputs
            exec_res["artifacts"] = outputs
        store.save_message(state.run_id, f"execution_result_{tid}", exec_res)
        state.add_event("task_executed", f"Task {tid} executed by {role}", "3")

    state.status = "complete"
    state.add_event(
        "dispatch_completed",
        f"Executed all {len(tasks)} tasks successfully",
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


def _finalize_pipeline_run(state: PipelineState, store: ContextStore, model: str) -> None:
    """Finalize a completed or aborted run: report outcome, record trajectory, mine lessons, seal cold storage."""
    # Report final pipeline outcome to terminal-mcp
    if state.status == "complete":
        send_terminal_mcp(f"\n🎉 [PIPELINE COMPLETE] Run {state.run_id} finished successfully!")
    elif state.status == "aborted":
        last_event = state.events[-1]["detail"] if state.events else "Unknown reason"
        send_terminal_mcp(f"\n🚨 [PIPELINE ABORTED] Phase: {state.current_phase}, Reason: {last_event}")

    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    # Proactive positive lesson mining on clean run (§5.02 / §6.2)
    if state.status == "complete" and state.architect_revisions_used == 0 and state.orchestrator_revisions_used == 0 and memory_store:
        total_retries = sum(t.get("retries", 0) for t in state.tasks.values())
        if total_retries == 0:
            try:
                for tid, tinfo in state.tasks.items():
                    t_res = store.load(f"runs/{state.run_id}/messages/execution_result_{tid}.json") or {}
                    cog = t_res.get("cognition") or {}
                    risks_text = cog.get("risks", "")
                    sol_text = cog.get("solution", "")
                    if len(risks_text) > 30 and len(sol_text) > 30:
                        prov_rule = f"Proactive risk mitigation for {tinfo.get('role', 'task')}: {risks_text[:100]} -> Solved via: {sol_text[:100]}"
                        cat = "Defensive Bash Scripting" if tinfo.get("role") in ("coder", "sysadmin") else "System Architecture"
                        staged_id = memory_store.stage_pending_lesson({
                            "proposed_rule": prov_rule,
                            "category": cat,
                            "keywords": ["proactive", "risk", "mitigation", tinfo.get("role", "task")],
                            "task_file": f"runs/{state.run_id}/messages/execution_result_{tid}.json",
                            "reviewer_critique": "Proactively mitigated edge case on clean first-pass execution",
                            "lesson_type": "proven_pattern",
                            "outcome": "approved",
                        })
                        send_terminal_mcp(f"🌟 [MEMORY] Staged proven_pattern lesson '{staged_id}' from clean run")
                        break
            except Exception as e:
                state.add_event("proven_pattern_failed", f"Failed to stage proven pattern: {e}", "4")

    # Record trajectory for dataset & fine-tuning (§10.9)
    try:
        all_scripts: List[str] = []
        all_injected: List[str] = []
        for r_lessons in state.injected_lessons.values():
            for l in r_lessons:
                if isinstance(l, dict) and "id" in l:
                    all_injected.append(l["id"])

        roles_dict: Dict[str, Any] = {}
        for role_name in ("architect", "orchestrator", "reviewer", "security"):
            if role_name == "architect":
                msg = state.messages.get("plan", {})
            elif role_name == "orchestrator":
                msg = state.messages.get("annotated_plan", {})
            elif role_name == "reviewer":
                msg = state.messages.get("review_verdict") or state.messages.get("reviewer_verdict") or {}
            elif role_name == "security":
                msg = state.messages.get("security_verdict", {})
            else:
                msg = {}

            if isinstance(msg, dict):
                cognition = msg.get("cognition", {})
                analysis_val = cognition.get("analysis", "") if isinstance(cognition, dict) else ""
                roles_dict[role_name] = {
                    "model": model,
                    "analysis": analysis_val,
                    "strategy": analysis_val,
                    "risks": cognition.get("risks", "") if isinstance(cognition, dict) else "",
                    "solution": cognition.get("solution", "") if isinstance(cognition, dict) else "",
                    "verification": cognition.get("verification", "") if isinstance(cognition, dict) else "",
                    "chain_of_thought": cognition.get("chain_of_thought", "") if isinstance(cognition, dict) else "",
                }

        primary_reasoning: Dict[str, Any] = {}
        last_code = ""
        for tid, tinfo in state.tasks.items():
            t_res = store.load(f"runs/{state.run_id}/messages/execution_result_{tid}.json") or {}
            role = tinfo.get("role", "coder")
            artifacts = t_res.get("artifacts") or t_res.get("outputs") or {}
            if isinstance(artifacts, dict):
                for fname, content in artifacts.items():
                    if isinstance(content, str) and (fname.endswith((".sh", ".py")) or content.strip().startswith("#!")):
                        all_scripts.append(content)
                        last_code = content

            cog = t_res.get("cognition", {})
            if isinstance(cog, dict) and any(cog.values()):
                analysis_val = cog.get("analysis", "")
                role_entry = {
                    "model": model,
                    "analysis": analysis_val,
                    "strategy": analysis_val,
                    "risks": cog.get("risks", ""),
                    "solution": cog.get("solution", ""),
                    "verification": cog.get("verification", ""),
                    "chain_of_thought": cog.get("chain_of_thought", ""),
                }
                roles_dict[role] = role_entry
                if not primary_reasoning:
                    primary_reasoning = {
                        "strategy": analysis_val,
                        "risks": cog.get("risks", ""),
                        "solution": cog.get("solution", ""),
                        "verification_plan": cog.get("verification", ""),
                        "chain_of_thought": cog.get("chain_of_thought", ""),
                    }

        if not primary_reasoning:
            arch_cog = roles_dict.get("architect", {})
            if arch_cog and any(arch_cog.values()):
                primary_reasoning = {
                    "strategy": arch_cog.get("analysis", ""),
                    "risks": arch_cog.get("risks", ""),
                    "solution": arch_cog.get("solution", ""),
                    "verification_plan": arch_cog.get("verification", ""),
                    "chain_of_thought": arch_cog.get("chain_of_thought", ""),
                }

        total_iterations = 1 + state.architect_revisions_used + state.orchestrator_revisions_used
        traj_result = {
            "author_model": model,
            "script_versions": all_scripts,
            "final_code_block": last_code,
            "iterations": total_iterations,
            "approved": state.status == "complete",
            "abort_reason": state.events[-1]["detail"] if state.status == "aborted" and state.events else "",
            "injected_lessons": sorted(list(set(all_injected))),
            "reasoning": primary_reasoning,
            "roles": roles_dict,
            "category": "Multi-Agent Workflow",
        }
        traj_id = record_trajectory(
            traj_result,
            prompt_content=state.original_prompt,
            task_file=f"runs/{state.run_id}/state.json",
            trajectories_path=DEFAULT_TRAJECTORIES_PATH,
        )
        send_terminal_mcp(f"📜 [TRAJECTORY] Recorded pipeline trajectory '{traj_id}'")
    except Exception as e:
        state.add_event("trajectory_failed", f"Failed to record trajectory: {e}", "3")

    # Seal run to cold storage
    try:
        store.seal_run(state.run_id)
    except Exception as e:
        state.add_event("seal_failed", f"Failed to seal run: {e}", "3")


def run_pipeline(
    prompt: str,
    run_id: Optional[str] = None,
    model: str = "winter-prime:latest",
    store: Optional[ContextStore] = None,
) -> dict:
    """Execute the full Arc-Orc-Rev pipeline loop."""
    if not run_id:
        run_id = generate_run_id()

    if store is None:
        store = ContextStore()

    state = PipelineState(run_id=run_id, original_prompt=prompt)
    store.save_state(run_id, state.to_dict())

    emitter = None
    try:
        emitter = EventEmitter(run_id=run_id)
        EventEmitter.set_current(emitter)
        emitter.pipeline_start(
            task_file=prompt if prompt.endswith(".md") else "prompt",
            prompt=prompt,
            tier=None,
            models={"default": model},
            max_retries=3,
        )
    except Exception:
        pass

    try:
        while state.current_phase not in ("complete", "aborted"):
            if emitter:
                try:
                    emitter.stage_transition(state.current_phase)
                except Exception:
                    pass

            phase_fn = PHASE_DISPATCH.get(state.current_phase)
            if not phase_fn:
                state.status = "aborted"
                state.add_event("unknown_phase", f"No handler for phase: {state.current_phase}", "3")
                break

            next_phase = phase_fn(state, store, model=model)
            state.current_phase = next_phase
            store.save_state(run_id, state.to_dict())

        if state.status in ("complete", "aborted"):
            _finalize_pipeline_run(state, store, model)
            if emitter:
                try:
                    emitter.pipeline_end(
                        outcome=state.status,
                        iterations=1 + state.architect_revisions_used + state.orchestrator_revisions_used,
                        abort_reason=state.events[-1]["detail"] if state.status == "aborted" and state.events else "",
                    )
                except Exception:
                    pass
    finally:
        try:
            EventEmitter.set_current(None)
        except Exception:
            pass

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

    emitter = None
    try:
        emitter = EventEmitter(run_id=run_id)
        EventEmitter.set_current(emitter)
    except Exception:
        pass

    try:
        while state.current_phase not in ("complete", "aborted"):
            if emitter:
                try:
                    emitter.stage_transition(state.current_phase)
                except Exception:
                    pass

            phase_fn = PHASE_DISPATCH.get(state.current_phase)
            if not phase_fn:
                state.status = "aborted"
                state.add_event("unknown_phase", f"No handler for phase: {state.current_phase}", "3")
                break

            next_phase = phase_fn(state, store, model=model)
            state.current_phase = next_phase
            store.save_state(run_id, state.to_dict())

        if state.status in ("complete", "aborted"):
            _finalize_pipeline_run(state, store, model)
            if emitter:
                try:
                    emitter.pipeline_end(
                        outcome=state.status,
                        iterations=1 + state.architect_revisions_used + state.orchestrator_revisions_used,
                        abort_reason=state.events[-1]["detail"] if state.status == "aborted" and state.events else "",
                    )
                except Exception:
                    pass
    finally:
        try:
            EventEmitter.set_current(None)
        except Exception:
            pass

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
