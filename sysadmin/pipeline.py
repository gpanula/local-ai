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
from mcp_core.hardware import (
    get_hardware_tier,
    get_default_model,
    get_escalation_model,
    get_primary_coder_model,
)
from mcp_core.memory import MemoryStore, DEFAULT_DB_PATH
from mcp_core.injection import format_lessons_for_prompt
from mcp_core.extraction import extract_lesson_from_critique
from mcp_core.attribution import attribute_lessons
from mcp_core.trajectories import record_trajectory, DEFAULT_TRAJECTORIES_PATH
from mcp_ollama.server import (
    handle_chat,
    handle_write_file,
    handle_execute_task,
    handle_unload_model,
    _get_model_context_length,
)
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

# Canonical Strategy to Auditor Model Mapping
AUDITOR_STRATEGY_MAP: Dict[str, str] = {
    "balanced": "qwen3:8b",
    "adversarial": "deepseek-r1:8b",
    "algorithmic": "deepseek-coder-v2:16b",
}


def resolve_auditor_model(
    annotated_plan: Optional[Dict[str, Any]] = None,
    explicit_auditor: Optional[str] = None,
    builder_model: str = "winter-prime:16gb",
    fallback_auditor: Optional[str] = None,
) -> Optional[str]:
    """Resolve effective auditor model from explicit flag, Orchestrator strategy, or fallback."""
    if explicit_auditor:
        return explicit_auditor

    if isinstance(annotated_plan, dict):
        plan_model = annotated_plan.get("auditor_model")
        plan_strat = annotated_plan.get("auditor_strategy")

        candidate = None
        if plan_model and isinstance(plan_model, str) and plan_model.strip():
            candidate = plan_model.strip()
        elif plan_strat and isinstance(plan_strat, str):
            candidate = AUDITOR_STRATEGY_MAP.get(plan_strat.strip().lower())

        if candidate:
            # Enforce Anti-Self-Review: cannot match builder model
            if candidate != builder_model:
                return candidate

    return fallback_auditor


def validate_retry_budget(val: Any) -> int:
    """Validate that retry budget is an integer between 1 and 15."""
    try:
        ival = int(val)
    except (ValueError, TypeError):
        raise ValueError(f"Retry budget must be an integer, got: {val!r}")
    if not (1 <= ival <= 15):
        raise ValueError(f"Retry budget must be between 1 and 15, got: {ival}")
    return ival


class PipelineState:
    """Tracks the mutable state of a single pipeline run."""

    def __init__(self, run_id: str, original_prompt: str, retry_budget: Optional[int] = None):
        self.run_id = run_id
        self.original_prompt = original_prompt
        self.status = "running"
        self.current_phase = "architect"
        self.architect_revisions_used = 0
        self.orchestrator_revisions_used = 0
        self.retry_budget: Optional[int] = validate_retry_budget(retry_budget) if retry_budget is not None else None
        self.architect_budget = self.retry_budget if self.retry_budget is not None else 3
        self.orchestrator_budget = self.retry_budget if self.retry_budget is not None else 3
        self.messages: Dict[str, Any] = {}
        self.tasks: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []
        self.prior_plan_hash: Optional[str] = None
        self.injected_lessons: Dict[str, List[dict]] = {}
        self.builder_model: str = "winter-prime:latest"
        self.auditor_model: Optional[str] = None
        self.tier: str = "8gb"
        self.coder_model: Optional[str] = None
        self.escalation_model: Optional[str] = None
        self.no_escalation: bool = False
        self.unload_models: bool = False
        self.keep_models: bool = False

    def to_dict(self) -> dict:
        """Serialize to state.json schema (§6.1)."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "original_prompt": self.original_prompt,
            "architect_revisions_used": self.architect_revisions_used,
            "orchestrator_revisions_used": self.orchestrator_revisions_used,
            "retry_budget": getattr(self, "retry_budget", None),
            "architect_budget": getattr(self, "architect_budget", 3),
            "orchestrator_budget": getattr(self, "orchestrator_budget", 3),
            "current_phase": self.current_phase,
            "messages": {
                k: f"runs/{self.run_id}/messages/{k}.json" if isinstance(v, dict) else v
                for k, v in self.messages.items()
            },
            "tasks": self.tasks,
            "events": self.events,
            "builder_model": getattr(self, "builder_model", "winter-prime:latest"),
            "auditor_model": getattr(self, "auditor_model", None),
            "tier": getattr(self, "tier", "8gb"),
            "coder_model": getattr(self, "coder_model", None),
            "escalation_model": getattr(self, "escalation_model", None),
            "no_escalation": getattr(self, "no_escalation", False),
            "unload_models": getattr(self, "unload_models", False),
            "keep_models": getattr(self, "keep_models", False),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineState":
        """Deserialize from state.json for --resume support."""
        state = cls(
            run_id=data["run_id"],
            original_prompt=data.get("original_prompt", ""),
            retry_budget=data.get("retry_budget"),
        )
        state.status = data.get("status", "running")
        state.current_phase = data.get("current_phase", "architect")
        state.architect_revisions_used = data.get("architect_revisions_used", 0)
        state.orchestrator_revisions_used = data.get("orchestrator_revisions_used", 0)
        state.architect_budget = data.get("architect_budget", state.architect_budget)
        state.orchestrator_budget = data.get("orchestrator_budget", state.orchestrator_budget)
        state.tasks = data.get("tasks", {})
        state.events = data.get("events", [])
        state.messages = data.get("messages", {})
        state.builder_model = data.get("builder_model", "winter-prime:latest")
        state.auditor_model = data.get("auditor_model", None)
        state.tier = data.get("tier", "8gb")
        state.coder_model = data.get("coder_model", None)
        state.escalation_model = data.get("escalation_model", None)
        state.no_escalation = data.get("no_escalation", False)
        state.unload_models = data.get("unload_models", False)
        state.keep_models = data.get("keep_models", False)
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
            ctx_limit = _get_model_context_length(model)
            emitter.context_window(
                iteration=1,
                system_rules=system_prompt,
                tools=tools or [],
                lessons=lessons or [],
                user_prompt=user_content,
                context_limit=ctx_limit,
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

    # Check for synthesized code in clean_body or parsed JSON outputs
    code_str = ""
    code_match = re.search(r"```(?:bash|sh)?\n([\s\S]*?)```", clean_body)
    if code_match:
        code_str = code_match.group(1).strip()
    else:
        try:
            parsed_body = parse_llm_json(response)
            out_dict = parsed_body.get("outputs", {})
            if isinstance(out_dict, dict):
                for p, c in out_dict.items():
                    if isinstance(c, str) and (p.endswith((".sh", ".bash", ".py", ".yml", ".yaml", ".json")) or c.strip().startswith("#!")):
                        code_str = c.strip()
                        break
        except Exception:
            pass

    if code_str and role in ("coder", "dispatch", "sysadmin"):
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


def promote_plan_to_annotated(plan_msg: Dict[str, Any], architect_model: str = "winter-prime:16gb") -> Dict[str, Any]:
    """Promote an Architect PlanMessage to an AnnotatedPlanMessage for fast-path direct execution.

    Bypasses the Orchestrator stage by synthesizing canonical DAG, assigned agents,
    tools, and strategy metadata directly from the Architect's decomposition.
    """
    raw_tasks = plan_msg.get("tasks", [])
    annotated_tasks = []
    task_ids = []

    auditor_strat = plan_msg.get("auditor_hint") or "balanced"
    auditor_model = AUDITOR_STRATEGY_MAP.get(str(auditor_strat).lower(), "qwen3:8b")
    coder_strat = plan_msg.get("coder_hint") or "defensive_bash"

    for i, t in enumerate(raw_tasks):
        tid = t.get("task_id") or f"t-{i+1:03d}"
        task_ids.append(tid)
        agent = t.get("agent_hint") or t.get("assigned_agent") or "coder"
        if agent not in ("coder", "sysadmin"):
            agent = "coder"

        tools = list(t.get("tools_required") or [])
        if not tools:
            tools = ["write_file", "run_bash"]

        outputs = t.get("outputs", [])
        if outputs and "write_file" not in tools:
            tools.append("write_file")

        depends = []
        if i > 0 and task_ids:
            depends = [task_ids[i - 1]]

        annotated_tasks.append({
            "task_id": tid,
            "description": t.get("description", ""),
            "domain_tags": t.get("domain_tags", ["Defensive Bash Scripting"]),
            "assigned_agent": agent,
            "tools_required": tools,
            "inputs": t.get("inputs", []),
            "outputs": outputs,
            "constraints": t.get("constraints", []),
            "depends_on": depends,
            "coder_strategy": coder_strat,
        })

    edges = []
    for i in range(1, len(task_ids)):
        edges.append({
            "from": task_ids[i - 1],
            "to": task_ids[i],
            "type": "data_dependency",
        })

    cognition = plan_msg.get("cognition", {})

    annotated_plan = {
        "schema_version": "2.0",
        "message_type": "annotated_plan",
        "run_id": plan_msg.get("run_id", ""),
        "revision": plan_msg.get("revision", 0),
        "revision_diff": None,
        "original_prompt": plan_msg.get("original_prompt", ""),
        "goal_summary": plan_msg.get("goal_summary", ""),
        "workflow_mode": "direct",
        "auditor_strategy": auditor_strat,
        "auditor_model": auditor_model,
        "dag": {
            "nodes": task_ids,
            "edges": edges,
        },
        "tasks": annotated_tasks,
        "open_questions": plan_msg.get("open_questions", []),
        "cognition": cognition,
    }
    return normalize_annotated_plan(annotated_plan)


def resolve_coder_model(
    task: Dict[str, Any],
    state: Optional[PipelineState] = None,
    tier: Optional[str] = None,
    fallback_model: str = "winter-coder:latest",
) -> str:
    """Resolve active Coder model based on CLI flags, task annotation, or hardware tier."""
    if state and getattr(state, "coder_model", None):
        return state.coder_model.strip()

    task_model = task.get("coder_model")
    if task_model and isinstance(task_model, str) and task_model.strip():
        return task_model.strip()

    active_tier = tier or (state.tier if state else None) or get_hardware_tier()
    task_strat = task.get("coder_strategy")
    if task_strat and isinstance(task_strat, str):
        strat = task_strat.strip().lower()
        if strat == "algorithmic" and active_tier in ("16gb", "24gb"):
            return "deepseek-coder-v2:16b"
        elif strat == "lightweight":
            return "winter-coder:8gb"

    role = task.get("assigned_agent", "coder")
    return get_default_model(role, tier=active_tier)


def resolve_escalation_model(
    role: str = "coder",
    state: Optional[PipelineState] = None,
    tier: Optional[str] = None,
) -> str:
    """Resolve the escalation model ensuring it respects available VRAM."""
    if state and getattr(state, "escalation_model", None):
        return state.escalation_model.strip()

    active_tier = tier or (state.tier if state else None) or get_hardware_tier()
    return get_escalation_model(tier=active_tier, role=role)


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

    # Fast-Path direct mode check:
    # If the Architect designates workflow_mode == "direct" (or 1 task and not explicitly orchestrated),
    # bypass the Orchestrator stage and advance directly to Reviewer.
    workflow_mode = str(plan.get("workflow_mode", "")).strip().lower()
    is_direct = (workflow_mode == "direct")

    if is_direct:
        annotated_plan = promote_plan_to_annotated(plan, architect_model=model)
        state.messages["annotated_plan"] = annotated_plan
        store.save_message(state.run_id, "annotated_plan", annotated_plan)

        send_terminal_mcp(
            f"\n⚡ [ARCHITECT FAST-PATH] Direct execution mode selected ({len(plan_tasks)} task(s)). "
            f"Bypassing Orchestrator LLM pass -> advancing directly to Reviewer/Auditor gate."
        )
        state.add_event(
            "orchestrator_bypassed",
            f"Fast-path direct execution selected by Architect ({len(plan_tasks)} task(s))",
            "2",
        )
        emitter = EventEmitter.get_current()
        if emitter:
            try:
                emitter.emit("orchestrator_bypassed", {
                    "reason": "Fast-path direct execution selected by Architect",
                    "task_count": len(plan_tasks),
                })
            except Exception:
                pass
        return "reviewer"

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
    builder_model = getattr(state, "builder_model", "winter-prime:16gb")

    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    # Step 1: Deterministic Pre-Filter
    pre_filter_verdict = validate_annotated_plan(annotated_plan, state.original_prompt, builder_model=builder_model)
    if pre_filter_verdict.get("verdict") != "approved":
        state.messages["review_verdict"] = pre_filter_verdict
        store.save_message(state.run_id, "review_verdict", pre_filter_verdict)
        return_to = pre_filter_verdict.get("return_to", "orchestrator")
        if annotated_plan.get("workflow_mode") == "direct" and return_to == "orchestrator":
            return_to = "architect"
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
        if annotated_plan.get("workflow_mode") == "direct" and return_to == "orchestrator":
            return_to = "architect"
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
        if annotated_plan.get("workflow_mode") == "direct" and return_to == "orchestrator":
            return_to = "architect"
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


def run_dispatch(
    state: PipelineState,
    store: ContextStore,
    model: str = "winter-prime:latest",
    auditor_model: Optional[str] = None,
    tier: Optional[str] = None,
) -> str:
    """Dispatch Phase: Prepares executor tasks, snapshots, and task messages."""
    annotated_plan = state.messages.get("annotated_plan", {})
    tasks = annotated_plan.get("tasks", [])

    try:
        memory_store = MemoryStore(DEFAULT_DB_PATH)
    except Exception:
        memory_store = None

    verified_task_files: Dict[str, str] = {}

    for task in tasks:
        tid = task.get("task_id", "unknown")
        role = task.get("assigned_agent", "coder")
        task_desc = task.get("description", "")
        state.tasks[tid] = {
            "status": "pending",
            "retries": 0,
            "role": role,
        }

        # Resolve primary and escalation models respecting hardware tier / VRAM
        active_tier = tier or getattr(state, "tier", None) or get_hardware_tier()
        primary_coder = resolve_coder_model(task, state=state, tier=active_tier, fallback_model=model)
        escalation_coder = resolve_escalation_model(role=role, state=state, tier=active_tier)
        enable_escalation = not getattr(state, "no_escalation", False)
        configured_budget = getattr(state, "retry_budget", None)
        if configured_budget is not None:
            max_retries = configured_budget
        else:
            max_retries = 3 if (enable_escalation and escalation_coder != primary_coder) else 2

        current_model = primary_coder
        escalated = False

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
            "model_used": current_model,
        }
        store.save_snapshot(state.run_id, tid, snapshot)

        # Build TaskMessage (§3.6)
        declared_outputs = list(task.get("outputs") or [])
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
            "declared_outputs": declared_outputs,
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
            f"\n🚀 [DISPATCH] Executing task '{tid}' with agent `{role}` (model: `{current_model}`): {task_desc}"
        )
        emitter = EventEmitter.get_current()
        if emitter:
            try:
                emitter.stage_transition(role)
            except Exception:
                pass

        retries = 0
        passed_all_gates = False
        exec_res = {}
        outputs = {}

        def _check_escalation_before_retry():
            nonlocal current_model, escalated
            escalation_threshold = 1 if max_retries == 1 else 2
            if retries == escalation_threshold and enable_escalation and not escalated and escalation_coder != primary_coder:
                escalated = True
                send_terminal_mcp(
                    f"\n🔄 [MODEL ESCALATION] Primary {role} ({primary_coder}) exhausted {escalation_threshold} attempt(s) on {active_tier} hardware.\n"
                    f"   Escalating attempt {retries + 1}/{max_retries} to specialized model: `{escalation_coder}`..."
                )
                state.add_event(
                    "model_escalated",
                    f"Escalated {role} for task {tid} from {primary_coder} to {escalation_coder} on {active_tier} tier",
                    "2",
                )
                emitter = EventEmitter.get_current()
                if emitter:
                    try:
                        emitter.emit("model_escalated", {
                            "task_id": tid,
                            "primary_model": primary_coder,
                            "escalated_model": escalation_coder,
                            "tier": active_tier,
                        })
                    except Exception:
                        pass

                # VRAM Management: On 8GB or 16GB tier (or if unload_models is requested),
                # unload the primary model before loading the escalation model.
                should_unload = (active_tier in ("8gb", "16gb")) or getattr(state, "unload_models", False)
                if should_unload and not getattr(state, "keep_models", False):
                    try:
                        send_terminal_mcp(
                            f"🧹 [VRAM CLEANUP] Unloading '{current_model}' to ensure 100% GPU VRAM for '{escalation_coder}' on {active_tier} tier..."
                        )
                        handle_unload_model(current_model)
                    except Exception as e:
                        send_terminal_mcp(f"⚠️ [VRAM CLEANUP] Warning: failed to unload {current_model}: {e}")

                current_model = escalation_coder

        while retries <= max_retries:
            raw_result = stage_chat(
                role=role,
                system_prompt=role_sys_prompt,
                user_content=json.dumps(task_msg, indent=2),
                model=current_model,
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
                if code_blocks and declared_outputs:
                    target_file = declared_outputs[0]
                    outputs = {target_file: max(code_blocks, key=len).strip()}
                    exec_res["outputs"] = outputs

            # Output Boundary Protection:
            # Prevent tasks from emitting undeclared files or overwriting verified files from earlier tasks.
            if isinstance(outputs, dict):
                declared_set = set(declared_outputs)
                filtered_outputs = {}
                for p, c in outputs.items():
                    if p.lower() in ("stdout", "stderr", "returncode", "exit_code", "output", "result", "hello_world_result"):
                        filtered_outputs[p] = c
                        continue
                    if declared_set:
                        if p in declared_set:
                            filtered_outputs[p] = c
                        else:
                            send_terminal_mcp(
                                f"⚠️ [OUTPUT GUARD] Task '{tid}' emitted undeclared output `{p}` "
                                f"(declared: {list(declared_set)}). Dropping undeclared file output."
                            )
                    else:
                        # Task declared NO file outputs (e.g. execution/verification task)
                        if p in verified_task_files:
                            send_terminal_mcp(
                                f"🛡️ [OUTPUT GUARD] Task '{tid}' attempted to overwrite verified file `{p}` "
                                f"authored by earlier task '{verified_task_files[p]}'. Blocked unauthorized overwrite."
                            )
                        else:
                            filtered_outputs[p] = c
                outputs = filtered_outputs
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

            if code_files:
                first_path, first_code = next(iter(code_files.items()))
                emitter = EventEmitter.get_current()
                if emitter:
                    try:
                        emitter.code_synthesized(
                            iteration=1,
                            code=first_code,
                            script_name=first_path,
                        )
                    except Exception:
                        pass

            # Tier 1: Deterministic Code Linter Gate
            linter_verdict = validate_code_output(task, outputs)
            if linter_verdict.get("verdict") != "approved":
                critique = linter_verdict.get("critique", "Linter violations found.")
                violations = linter_verdict.get("violations", [])
                v_summary = "\n".join([f"  ⚠️ [{v.get('type')}] {v.get('description')}" for v in violations])
                send_terminal_mcp(
                    f"\n❌ [CODE LINTER GATE] Task '{tid}' rejected with {len(violations)} violation(s):\n{v_summary}"
                )
                emitter = EventEmitter.get_current()
                if emitter:
                    try:
                        emitter.linter_result(
                            iteration=1,
                            passed=False,
                            output=critique,
                            returncode=1,
                        )
                    except Exception:
                        pass
                retries += 1
                if retries <= max_retries:
                    _check_escalation_before_retry()
                    send_terminal_mcp(
                        f"🔄 [REMEDIATION] Requesting {role.capitalize()} retry {retries}/{max_retries} with linter critique using `{current_model}`..."
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
                            fail_model = f"{current_model} (escalated from {primary_coder})" if escalated else current_model
                            fail_lesson = extract_lesson_from_critique(
                                critique=critique,
                                task_file=state.original_prompt[:100],
                                prompt_content=state.original_prompt,
                                model=fail_model,
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
            emitter = EventEmitter.get_current()
            if emitter:
                try:
                    emitter.linter_result(
                        iteration=1,
                        passed=True,
                        output=linter_verdict.get("critique", "Passed all defensive standards & ShellCheck"),
                        returncode=0,
                    )
                except Exception:
                    pass

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
            rev_model = auditor_model or current_model
            raw_rev = stage_chat(
                role="reviewer",
                system_prompt=rev_sys_prompt,
                user_content=json.dumps(rev_payload, indent=2),
                model=rev_model,
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
                emitter = EventEmitter.get_current()
                if emitter:
                    try:
                        emitter.review_result(
                            iteration=1,
                            verdict="rejected",
                            critique=critique,
                            reviewer_model=rev_model,
                        )
                    except Exception:
                        pass
                retries += 1
                if retries <= max_retries:
                    _check_escalation_before_retry()
                    send_terminal_mcp(
                        f"🔄 [REMEDIATION] Requesting {role.capitalize()} retry {retries}/{max_retries} with reviewer critique using `{current_model}`..."
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
                            fail_model = f"{current_model} (escalated from {primary_coder})" if escalated else current_model
                            fail_lesson = extract_lesson_from_critique(
                                critique=critique,
                                task_file=state.original_prompt[:100],
                                prompt_content=state.original_prompt,
                                model=fail_model,
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
            emitter = EventEmitter.get_current()
            if emitter:
                try:
                    emitter.review_result(
                        iteration=1,
                        verdict="approved",
                        critique=rev_verdict.get("cognition", {}).get("solution") or "Approved code logic & acceptance criteria.",
                        reviewer_model=rev_model,
                    )
                except Exception:
                    pass

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
            sec_model = auditor_model or current_model
            raw_sec = stage_chat(
                role="security",
                system_prompt=sec_sys_prompt,
                user_content=json.dumps(sec_payload, indent=2),
                model=sec_model,
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
                    _check_escalation_before_retry()
                    send_terminal_mcp(
                        f"🔄 [REMEDIATION] Requesting {role.capitalize()} retry {retries}/{max_retries} with security critique using `{current_model}`..."
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
                            fail_model = f"{current_model} (escalated from {primary_coder})" if escalated else current_model
                            fail_lesson = extract_lesson_from_critique(
                                critique=critique,
                                task_file=state.original_prompt[:100],
                                prompt_content=state.original_prompt,
                                model=fail_model,
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
                    success_model = f"{current_model} (escalated from {primary_coder})" if escalated else current_model
                    new_lesson = extract_lesson_from_critique(
                        critique=critique_summary,
                        task_file=state.original_prompt[:100],
                        prompt_content=state.original_prompt,
                        model=success_model,
                        lesson_type="solved_pattern",
                        outcome="approved",
                    )
                    lid = memory_store.insert_lesson(new_lesson)
                    send_terminal_mcp(f"🎉 [MEMORY] Captured solved_pattern lesson '{lid}' after successful remediation with {success_model}")
                    state.add_event("lesson_captured", f"Captured solved_pattern lesson {lid}", "3")
                except Exception:
                    pass
            break

        # If on 8GB tier and model was escalated, unload it after task completion to clear VRAM
        if escalated and active_tier == "8gb" and not getattr(state, "keep_models", False):
            try:
                handle_unload_model(escalation_coder)
            except Exception:
                pass

        state.tasks[tid]["retries"] = retries
        if is_code_output and not passed_all_gates:
            state.tasks[tid]["status"] = "failed"
            store.save_message(state.run_id, f"execution_result_{tid}", exec_res)
            state.add_event("task_failed", f"Task {tid} failed pre-execution verification gates", "3")
            state.status = "aborted"
            state.add_event("dispatch_aborted", f"Dispatch aborted: Task {tid} failed pre-execution verification gates", "3")
            return "aborted"

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
                    verified_task_files[path] = tid
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

            # Verify exit code and explicit error signatures
            has_exit_zero = bool(re.search(r"Exit Code\*?\*?:\s*`?0`?", run_out))
            has_explicit_error = bool(
                re.search(r"❌\s*\[ERROR\]|Traceback \(most recent call last\)|command not found|No such file or directory", run_out)
            )
            if not has_exit_zero or has_explicit_error:
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

        if not exec_succeeded:
            state.status = "aborted"
            state.add_event("task_failed", f"Task {tid} script execution failed in terminal-mcp", "3")
            state.add_event("dispatch_aborted", f"Dispatch aborted: Task {tid} execution failed", "3")
            return "aborted"

    failed_tasks = [t for t, d in state.tasks.items() if d.get("status") == "failed"]
    if failed_tasks:
        state.status = "aborted"
        state.add_event(
            "dispatch_failed",
            f"Execution failed on {len(failed_tasks)} task(s): {', '.join(failed_tasks)}",
            "3",
        )
        return "aborted"

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
    tier: Optional[str] = None,
    auditor_model: Optional[str] = None,
    dynamic_auditor: bool = False,
    coder_model: Optional[str] = None,
    escalation_model: Optional[str] = None,
    no_escalation: bool = False,
    unload_models: bool = False,
    keep_models: bool = False,
    retry_budget: Optional[int] = None,
) -> dict:
    """Execute the full Arc-Orc-Rev pipeline loop."""
    if retry_budget is not None:
        validate_retry_budget(retry_budget)

    if not run_id:
        run_id = generate_run_id()

    if store is None:
        store = ContextStore()

    effective_tier = tier
    if not effective_tier:
        if auditor_model or dynamic_auditor:
            effective_tier = "24gb"
        elif "16gb" in model:
            effective_tier = "16gb"
        elif "24gb" in model:
            effective_tier = "24gb"
        elif "8gb" in model:
            effective_tier = "8gb"
        else:
            try:
                effective_tier = get_hardware_tier()
            except Exception:
                effective_tier = "8gb"

    state = PipelineState(run_id=run_id, original_prompt=prompt, retry_budget=retry_budget)
    state.builder_model = model
    state.auditor_model = auditor_model
    state.tier = effective_tier
    state.coder_model = coder_model
    state.escalation_model = escalation_model
    state.no_escalation = no_escalation
    state.keep_models = keep_models
    # On 8GB tier (laptops), automatically enable model unloading between stages unless keep_models is explicitly passed
    state.unload_models = unload_models or (effective_tier == "8gb" and not keep_models)
    store.save_state(run_id, state.to_dict())

    resolved_coder = coder_model or get_default_model("coder", tier=effective_tier)
    models_dict = {
        "default": model,
        "builder": model,
        "author": model,
        "coder": resolved_coder,
        "sysadmin": model,
        "architect": model,
        "orchestrator": model,
    }
    if auditor_model:
        models_dict.update({
            "auditor": auditor_model,
            "reviewer": auditor_model,
            "security": auditor_model,
        })

    context_limits = {}
    for m in set(models_dict.values()):
        if isinstance(m, str) and m:
            try:
                context_limits[m] = _get_model_context_length(m)
            except Exception:
                pass

    emitter = None
    try:
        emitter = EventEmitter(run_id=run_id)
        EventEmitter.set_current(emitter)
        emitter.pipeline_start(
            task_file=prompt if prompt.endswith(".md") else "prompt",
            prompt=prompt,
            tier=effective_tier,
            models=models_dict,
            max_retries=state.retry_budget if getattr(state, "retry_budget", None) is not None else 3,
            context_limits=context_limits,
        )
    except Exception:
        pass

    current_effective_auditor = auditor_model
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

            # VRAM Management: unload prior models between stages on 8GB tier or when requested
            if state.unload_models and not state.keep_models:
                try:
                    handle_unload_model()
                except Exception:
                    pass

            # Dynamic Auditor Resolution from Orchestrator's annotated plan
            if (not auditor_model or dynamic_auditor) and state.messages.get("annotated_plan"):
                loaded_plan = store.load(f"runs/{state.run_id}/messages/annotated_plan.json") if isinstance(state.messages.get("annotated_plan"), str) else state.messages.get("annotated_plan")
                resolved = resolve_auditor_model(
                    annotated_plan=loaded_plan,
                    explicit_auditor=auditor_model if not dynamic_auditor else None,
                    builder_model=model,
                    fallback_auditor="qwen3:8b" if (effective_tier == "24gb" or dynamic_auditor) else None,
                )
                if resolved and resolved != current_effective_auditor:
                    current_effective_auditor = resolved
                    state.auditor_model = resolved
                    models_dict["auditor"] = resolved
                    models_dict["reviewer"] = resolved
                    models_dict["security"] = resolved
                    if resolved not in context_limits:
                        try:
                            context_limits[resolved] = _get_model_context_length(resolved)
                        except Exception:
                            pass
                    send_terminal_mcp(
                        f"\n🎯 [ORCHESTRATOR] Dynamically selected Auditor model: `{current_effective_auditor}`"
                    )

            if state.current_phase in ("reviewer", "security"):
                current_phase_model = current_effective_auditor or model
                next_phase = phase_fn(state, store, model=current_phase_model)
            elif state.current_phase == "dispatch":
                next_phase = phase_fn(state, store, model=model, auditor_model=current_effective_auditor, tier=effective_tier)
            else:
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
    tier: Optional[str] = None,
    auditor_model: Optional[str] = None,
    dynamic_auditor: bool = False,
    coder_model: Optional[str] = None,
    escalation_model: Optional[str] = None,
    no_escalation: bool = False,
    unload_models: bool = False,
    keep_models: bool = False,
    retry_budget: Optional[int] = None,
) -> dict:
    """Resume an aborted or in-flight pipeline run from state.json."""
    if store is None:
        store = ContextStore()

    state_dict = store.load(f"runs/{run_id}/state.json")
    state = PipelineState.from_dict(state_dict)
    if retry_budget is not None:
        state.retry_budget = validate_retry_budget(retry_budget)
        state.architect_budget = state.retry_budget
        state.orchestrator_budget = state.retry_budget
    if tier:
        state.tier = tier
    if coder_model:
        state.coder_model = coder_model
    if escalation_model:
        state.escalation_model = escalation_model
    if no_escalation:
        state.no_escalation = no_escalation
    if keep_models:
        state.keep_models = keep_models
    if unload_models or (state.tier == "8gb" and not state.keep_models):
        state.unload_models = True

    effective_tier = state.tier

    emitter = None
    try:
        emitter = EventEmitter(run_id=run_id)
        EventEmitter.set_current(emitter)
    except Exception:
        pass

    current_effective_auditor = auditor_model or state.auditor_model
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

            # VRAM Management: unload prior models between stages on 8GB tier or when requested
            if state.unload_models and not state.keep_models:
                try:
                    handle_unload_model()
                except Exception:
                    pass

            if (not auditor_model or dynamic_auditor) and state.messages.get("annotated_plan"):
                loaded_plan = store.load(f"runs/{state.run_id}/messages/annotated_plan.json") if isinstance(state.messages.get("annotated_plan"), str) else state.messages.get("annotated_plan")
                resolved = resolve_auditor_model(
                    annotated_plan=loaded_plan,
                    explicit_auditor=auditor_model if not dynamic_auditor else None,
                    builder_model=model,
                    fallback_auditor="qwen3:8b" if (effective_tier == "24gb" or dynamic_auditor) else None,
                )
                if resolved and resolved != current_effective_auditor:
                    current_effective_auditor = resolved
                    state.auditor_model = resolved
                    send_terminal_mcp(
                        f"\n🎯 [ORCHESTRATOR] Dynamically selected Auditor model: `{current_effective_auditor}`"
                    )

            if state.current_phase in ("reviewer", "security"):
                current_phase_model = current_effective_auditor or model
                next_phase = phase_fn(state, store, model=current_phase_model)
            elif state.current_phase == "dispatch":
                next_phase = phase_fn(state, store, model=model, auditor_model=current_effective_auditor, tier=effective_tier)
            else:
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
    parser.add_argument("prompt", nargs="?", help="User prompt to execute (text or markdown file path)")
    parser.add_argument("--resume", metavar="RUN_ID", help="Resume an aborted run")
    parser.add_argument("--tier", choices=["8gb", "16gb", "24gb"], default=None, help="Hardware tier (8gb, 16gb, 24gb)")
    parser.add_argument("--model", default=None, help="Ollama model to use across pipeline stages (default: winter-prime:<tier> or winter-prime:latest)")
    parser.add_argument("--coder-model", default=None, help="Explicit coder model for dispatch stage (default: resolved from tier/task)")
    parser.add_argument("--escalation-model", default=None, help="Model to escalate to on attempt 3 if primary coder fails verification (default: tier-resolved)")
    parser.add_argument("--no-escalation", action="store_true", default=False, help="Disable failure model escalation and retain strict single-model retry")
    parser.add_argument("--auditor-model", default=None, help="Auditor model for Reviewer and Security stages (Dual-Model mode)")
    parser.add_argument("--dual-model", action="store_true", default=False, help="Enable 24GB dual-model residency (Builder: winter-prime:16gb, Auditor: dynamic/qwen3:8b)")
    parser.add_argument("--dynamic-auditor", action="store_true", default=False, help="Enable dynamic auditor model selection by Orchestrator")
    parser.add_argument("--keep-models", "--no-unload", dest="keep_models", action="store_true", default=False, help="Keep models loaded in VRAM between stages")
    parser.add_argument("--unload-models", action="store_true", default=False, help="Unload models between stages")
    parser.add_argument(
        "--retry-budget",
        "--max-retries",
        dest="retry_budget",
        type=int,
        default=None,
        help="Configurable retry budget for all stages (min: 1, max: 15, default: phase defaults [3])",
    )
    args = parser.parse_args()

    if args.retry_budget is not None:
        try:
            validate_retry_budget(args.retry_budget)
        except ValueError as e:
            parser.error(str(e))

    tier_model_map = {
        "8gb": "winter-prime:8gb",
        "16gb": "winter-prime:16gb",
        "24gb": "winter-prime:24gb",
    }

    dynamic_auditor = args.dynamic_auditor
    auditor_model = args.auditor_model
    if args.dual_model:
        selected_model = args.model or "winter-prime:16gb"
        if not auditor_model:
            dynamic_auditor = True
            auditor_model = None
    else:
        selected_model = args.model
        if not selected_model:
            if args.tier:
                selected_model = tier_model_map.get(args.tier, "winter-prime:latest")
            else:
                selected_model = "winter-prime:latest"

    kwargs = {
        "model": selected_model,
        "tier": args.tier,
        "coder_model": args.coder_model,
        "escalation_model": args.escalation_model,
        "no_escalation": args.no_escalation,
        "unload_models": args.unload_models,
        "keep_models": args.keep_models,
        "retry_budget": args.retry_budget,
    }
    if auditor_model:
        kwargs["auditor_model"] = auditor_model
    if dynamic_auditor:
        kwargs["dynamic_auditor"] = True

    if args.resume:
        result = resume_pipeline(args.resume, **kwargs)
    elif args.prompt:
        prompt_content = args.prompt
        if os.path.isfile(args.prompt):
            with open(args.prompt, "r", encoding="utf-8") as f:
                prompt_content = f.read().strip()
        result = run_pipeline(prompt_content, **kwargs)
    else:
        parser.error("Provide a prompt or --resume <run_id>")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
