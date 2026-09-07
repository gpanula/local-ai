"""Deterministic Pre-Filter for AnnotatedPlanMessage.

Fast Python validator that runs before the LLM Reviewer. Implements deterministic
checks from RFC v7 §4.3 (Steps 1-5, 7, 9). If any check fails, returns a ReviewVerdict
immediately without invoking the LLM Reviewer.
"""

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from mcp_core.workspace import WORKSPACE_ROOT

# Constants for cognition checks
PILLAR_FIELDS = ["analysis", "risks", "solution", "verification"]
PILLAR_MAP = {
    "analysis": "1",
    "risks": "2",
    "solution": "3",
    "verification": "4",
}
PLACEHOLDERS = {
    "none",
    "n/a",
    "ok",
    "null",
    "not applicable",
    "tbd",
    "todo",
    "placeholder",
}
MIN_COGNITION_LENGTH = 30


# ---------------------------------------------------------------------------
# Registry loading helpers (§2.1)
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    """Read and parse a JSON file. Raise FileNotFoundError with the path if missing."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Registry file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_tool_registry() -> dict:
    """Load sysadmin/data/registries/tools.json. Return the full dict."""
    path = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "registries", "tools.json")
    return _load_json(path)


def load_agent_registry() -> dict:
    """Load sysadmin/data/registries/agents.json. Return the full dict."""
    path = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "registries", "agents.json")
    return _load_json(path)


def load_rules_registry() -> dict:
    """Load sysadmin/data/registries/rules.json. Return the full dict."""
    path = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "registries", "rules.json")
    return _load_json(path)


def load_taxonomy() -> dict:
    """Load ollama_update/taxonomy.json. Return the full dict."""
    path = os.path.join(WORKSPACE_ROOT, "ollama_update", "taxonomy.json")
    return _load_json(path)


# ---------------------------------------------------------------------------
# Violation builder (§2.2)
# ---------------------------------------------------------------------------

def _violation(
    violation_id: str,
    vtype: str,
    description: str,
    severity: str = "blocking",
    task_id: Optional[str] = None,
    rule_ref: Optional[str] = None,
    tool_ref: Optional[str] = None,
    domain_ref: Optional[str] = None,
    pillar_ref: Optional[str] = None,
) -> dict:
    """Return a violation dict matching the ReviewVerdict.violations[] schema from §3.4."""
    return {
        "violation_id": violation_id,
        "type": vtype,
        "task_id": task_id,
        "rule_ref": rule_ref,
        "tool_ref": tool_ref,
        "domain_ref": domain_ref,
        "pillar_ref": pillar_ref,
        "description": description,
        "severity": severity,
    }


# ---------------------------------------------------------------------------
# Check functions (§2.3)
# ---------------------------------------------------------------------------

def check_schema(msg: dict) -> List[dict]:
    """Check 1: Verify schema conformance of AnnotatedPlanMessage."""
    violations: List[dict] = []

    # Required top-level fields
    if msg.get("schema_version") != "2.0":
        violations.append(
            _violation(
                "",
                "schema_error",
                f"Invalid or missing schema_version: expected '2.0', got {msg.get('schema_version')!r}",
                pillar_ref="3",
            )
        )

    if msg.get("message_type") != "annotated_plan":
        violations.append(
            _violation(
                "",
                "schema_error",
                f"Invalid or missing message_type: expected 'annotated_plan', got {msg.get('message_type')!r}",
                pillar_ref="3",
            )
        )

    run_id = msg.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        violations.append(
            _violation(
                "",
                "schema_error",
                "Missing or empty required top-level field: run_id",
                pillar_ref="3",
            )
        )

    original_prompt = msg.get("original_prompt")
    if not isinstance(original_prompt, str) or not original_prompt.strip():
        violations.append(
            _violation(
                "",
                "schema_error",
                "Missing or empty required top-level field: original_prompt",
                pillar_ref="3",
            )
        )

    dag = msg.get("dag")
    if not isinstance(dag, dict) or not isinstance(dag.get("nodes"), list) or not isinstance(dag.get("edges"), list):
        violations.append(
            _violation(
                "",
                "schema_error",
                "Field 'dag' must be an object with 'nodes' (list) and 'edges' (list)",
                pillar_ref="3",
            )
        )

    tasks = msg.get("tasks")
    if not isinstance(tasks, list) or len(tasks) == 0:
        violations.append(
            _violation(
                "",
                "schema_error",
                "Field 'tasks' must be a non-empty list",
                pillar_ref="3",
            )
        )
    else:
        # Check required task fields
        for idx, task in enumerate(tasks):
            if not isinstance(task, dict):
                violations.append(
                    _violation(
                        "",
                        "schema_error",
                        f"Task at index {idx} must be a dictionary",
                        pillar_ref="3",
                    )
                )
                continue

            tid = task.get("task_id")
            required_task_keys = [
                ("task_id", str),
                ("description", str),
                ("domain_tags", list),
                ("assigned_agent", str),
                ("tools_required", list),
            ]
            for key, expected_type in required_task_keys:
                val = task.get(key)
                if val is None or not isinstance(val, expected_type):
                    violations.append(
                        _violation(
                            "",
                            "schema_error",
                            f"Task '{tid or f'index-{idx}'}' missing or invalid field '{key}' (expected {expected_type.__name__})",
                            task_id=tid if isinstance(tid, str) else None,
                            pillar_ref="3",
                        )
                    )

    if not isinstance(msg.get("cognition"), dict):
        violations.append(
            _violation(
                "",
                "schema_error",
                "Field 'cognition' must be a dictionary containing 4 pillars",
                pillar_ref="3",
            )
        )

    return violations


def check_tools(msg: dict, tool_registry: dict) -> List[dict]:
    """Check 2: Verify all requested tools exist in the Tool Registry."""
    violations: List[dict] = []
    valid_tools: Set[str] = {t.get("name") for t in tool_registry.get("tools", []) if "name" in t}

    tasks = msg.get("tasks", [])
    if not isinstance(tasks, list):
        return violations

    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = task.get("task_id")
        tools_required = task.get("tools_required", [])
        if not isinstance(tools_required, list):
            continue

        for tool in tools_required:
            if not isinstance(tool, str) or tool not in valid_tools:
                violations.append(
                    _violation(
                        "",
                        "invalid_tool",
                        f"Tool '{tool}' is not declared in Tool Registry",
                        task_id=tid,
                        tool_ref=str(tool),
                        pillar_ref="3",
                    )
                )

    return violations


def check_agents(msg: dict, agent_registry: dict) -> List[dict]:
    """Check 3: Verify all assigned agents exist in the Agent Registry."""
    violations: List[dict] = []
    valid_agents: Set[str] = {a.get("type") for a in agent_registry.get("agents", []) if "type" in a}

    tasks = msg.get("tasks", [])
    if not isinstance(tasks, list):
        return violations

    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = task.get("task_id")
        agent = task.get("assigned_agent")
        if not isinstance(agent, str) or agent not in valid_agents:
            violations.append(
                _violation(
                    "",
                    "unknown_agent",
                    f"Agent '{agent}' is not declared in Agent Registry",
                    task_id=tid,
                    pillar_ref="3",
                )
            )

    return violations


def check_domain_tags(msg: dict, taxonomy: dict) -> List[dict]:
    """Check 4: Verify domain tags belong to canonical taxonomy."""
    violations: List[dict] = []
    canonical_domains: Set[str] = set(taxonomy.get("taxonomies", {}).keys())

    tasks = msg.get("tasks", [])
    if not isinstance(tasks, list):
        return violations

    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = task.get("task_id")
        tags = task.get("domain_tags")

        if not isinstance(tags, list) or len(tags) == 0:
            violations.append(
                _violation(
                    "",
                    "domain_tag_missing",
                    f"Task '{tid}' must carry at least one domain tag from taxonomy.json",
                    task_id=tid,
                    rule_ref="R-005",
                    pillar_ref="1",
                )
            )
            continue

        for tag in tags:
            if not isinstance(tag, str) or tag not in canonical_domains:
                violations.append(
                    _violation(
                        "",
                        "domain_tag_missing",
                        f"Domain tag '{tag}' is not a canonical domain in taxonomy.json",
                        task_id=tid,
                        domain_ref=str(tag),
                        rule_ref="R-005",
                        pillar_ref="1",
                    )
                )

    return violations


def check_dag(msg: dict) -> List[dict]:
    """Check 5: Verify DAG acyclicity and consistency between tasks and DAG nodes."""
    violations: List[dict] = []
    dag = msg.get("dag")
    if not isinstance(dag, dict):
        return violations

    nodes = dag.get("nodes", [])
    edges = dag.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return violations

    node_set = set(nodes)

    # 1. Verify task list matches DAG node list
    tasks = msg.get("tasks", [])
    task_ids = {t.get("task_id") for t in tasks if isinstance(t, dict) and "task_id" in t}

    missing_in_dag = task_ids - node_set
    for tid in sorted(missing_in_dag):
        violations.append(
            _violation(
                "",
                "dag_error",
                f"Task '{tid}' is in task list but missing from dag.nodes",
                task_id=tid,
                pillar_ref="4",
            )
        )

    missing_in_tasks = node_set - task_ids
    for tid in sorted(missing_in_tasks):
        violations.append(
            _violation(
                "",
                "dag_error",
                f"Node '{tid}' in dag.nodes has no matching task in tasks list",
                task_id=tid,
                pillar_ref="4",
            )
        )

    # 2. Build adjacency list and detect cycles
    adj: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        u = edge.get("from")
        v = edge.get("to")
        if u and v:
            adj[u].append(v)

    # DFS state: 0 = unvisited, 1 = visiting (in stack), 2 = visited
    state: Dict[str, int] = {}
    cycle_nodes: List[str] = []

    def dfs(curr: str, path: List[str]) -> bool:
        state[curr] = 1  # visiting
        path.append(curr)

        for neighbor in adj.get(curr, []):
            if state.get(neighbor) == 1:
                # Cycle detected
                cycle_start = path.index(neighbor)
                cycle_nodes.extend(path[cycle_start:] + [neighbor])
                return True
            elif state.get(neighbor, 0) == 0:
                if dfs(neighbor, path):
                    return True

        path.pop()
        state[curr] = 2  # visited
        return False

    all_graph_nodes = sorted(list(node_set.union(set(adj.keys()))))
    for node in all_graph_nodes:
        if state.get(node, 0) == 0:
            if dfs(node, []):
                cycle_str = " -> ".join(cycle_nodes)
                violations.append(
                    _violation(
                        "",
                        "dag_error",
                        f"Cycle detected in DAG: {cycle_str}",
                        pillar_ref="4",
                    )
                )
                break

    return violations


def check_prompt_fidelity(msg: dict, frozen_prompt: str) -> List[dict]:
    """Check 7: Verify prompt fidelity against frozen original prompt."""
    violations: List[dict] = []
    plan_prompt = msg.get("original_prompt", "")
    if not isinstance(plan_prompt, str):
        plan_prompt = ""

    plan_hash = hashlib.sha256(plan_prompt.encode("utf-8")).hexdigest()
    frozen_hash = hashlib.sha256(frozen_prompt.encode("utf-8")).hexdigest()

    if plan_hash != frozen_hash:
        violations.append(
            _violation(
                "",
                "rule_violation",
                "Plan original_prompt does not match frozen prompt hash",
                rule_ref="prompt_fidelity",
                pillar_ref="1",
            )
        )

    return violations


def check_cognition_substance(msg: dict) -> List[dict]:
    """Check 9: Verify 4-pillar completeness and substance."""
    violations: List[dict] = []

    def _validate_block(cog: Any, context_desc: str, task_id: Optional[str] = None):
        if not isinstance(cog, dict):
            violations.append(
                _violation(
                    "",
                    "rule_violation",
                    f"{context_desc} missing required cognition block",
                    task_id=task_id,
                    rule_ref="R-006",
                    pillar_ref=None,
                )
            )
            return

        for field in PILLAR_FIELDS:
            pillar_num = PILLAR_MAP[field]
            val = cog.get(field)
            if not isinstance(val, str) or not val.strip():
                violations.append(
                    _violation(
                        "",
                        "rule_violation",
                        f"{context_desc} missing required cognition.{field} field",
                        task_id=task_id,
                        rule_ref="R-006",
                        pillar_ref=pillar_num,
                    )
                )
            elif val.strip().lower() in PLACEHOLDERS:
                violations.append(
                    _violation(
                        "",
                        "rule_violation",
                        f"{context_desc} cognition.{field} contains placeholder evasion: '{val.strip()}'",
                        task_id=task_id,
                        rule_ref="R-006",
                        pillar_ref=pillar_num,
                    )
                )
            elif len(val.strip()) < MIN_COGNITION_LENGTH:
                violations.append(
                    _violation(
                        "",
                        "rule_violation",
                        f"{context_desc} cognition.{field} too short ({len(val.strip())} chars < {MIN_COGNITION_LENGTH})",
                        task_id=task_id,
                        rule_ref="R-006",
                        pillar_ref=pillar_num,
                    )
                )

    # Check top-level cognition
    _validate_block(msg.get("cognition"), "AnnotatedPlanMessage")

    # Check task-level cognition if present
    tasks = msg.get("tasks", [])
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict) and "cognition" in task:
                tid = task.get("task_id", "unknown")
                _validate_block(task.get("cognition"), f"Task '{tid}'", task_id=tid)

    return violations


# ---------------------------------------------------------------------------
# Main Orchestrator Function (§2.4)
# ---------------------------------------------------------------------------

def validate_annotated_plan(msg: dict, frozen_prompt: str) -> dict:
    """Run all deterministic checks. Return a ReviewVerdict dict matching §3.4.

    If all checks pass, return verdict="approved" with empty violations list.
    If any check fails, return verdict="rejected_tools" or "rejected_rules"
    based on violation types.
    """
    tool_registry = load_tool_registry()
    agent_registry = load_agent_registry()
    _rules_registry = load_rules_registry()
    taxonomy = load_taxonomy()

    all_violations: List[dict] = []
    all_violations.extend(check_schema(msg))
    all_violations.extend(check_tools(msg, tool_registry))
    all_violations.extend(check_agents(msg, agent_registry))
    all_violations.extend(check_domain_tags(msg, taxonomy))
    all_violations.extend(check_dag(msg))
    all_violations.extend(check_prompt_fidelity(msg, frozen_prompt))
    all_violations.extend(check_cognition_substance(msg))

    # Assign violation IDs
    for idx, v in enumerate(all_violations, start=1):
        v["violation_id"] = f"v-{idx:03d}"

    # Determine verdict and routing
    if not all_violations:
        verdict = "approved"
        return_to = None
        analysis = "Deterministic pre-filter validation of AnnotatedPlanMessage passed with zero violations."
        risks = "No deterministic structural, registry, DAG, prompt fidelity, or cognition substance risks detected."
        solution = "Plan is cleared to proceed to next review stage."
        verification = "All 7 deterministic checks executed cleanly."
    else:
        has_invalid_tool = any(v.get("type") == "invalid_tool" for v in all_violations)
        if has_invalid_tool:
            verdict = "rejected_tools"
            return_to = "architect"
        else:
            verdict = "rejected_rules"
            return_to = "orchestrator"

        unique_types = sorted(list({v.get("type", "unknown") for v in all_violations}))
        analysis = (
            f"Deterministic pre-filter identified {len(all_violations)} violation(s) across categories: "
            f"{', '.join(unique_types)}."
        )
        risks = (
            f"Executing this plan directly would violate registry constraints or schema boundaries: "
            f"{len(all_violations)} blocking issue(s) detected."
        )
        solution = (
            f"Return plan to {return_to} for remediation of reported violations before LLM review."
        )
        verification = "Deterministic checks flagged blocking discrepancies against registries and standards."

    return {
        "schema_version": "2.0",
        "message_type": "review_verdict",
        "run_id": msg.get("run_id", ""),
        "revision": msg.get("revision", 0),
        "verdict": verdict,
        "return_to": return_to,
        "violations": all_violations,
        "cognition": {
            "analysis": analysis,
            "risks": risks,
            "solution": solution,
            "verification": verification,
        },
    }
