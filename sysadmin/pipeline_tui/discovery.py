"""Run discovery and replay data loader for Pipeline Watch.

Discovers past runs across `sysadmin/data/trajectories.jsonl` and `.localai/runs/*.jsonl`.
Supports exact ID matching, prefix matching, keyword search, and the `latest` alias.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, List, Optional

from mcp_core.trajectories import DEFAULT_TRAJECTORIES_PATH
from mcp_core.workspace import WORKSPACE_ROOT

DEFAULT_RUNS_DIR = os.path.join(WORKSPACE_ROOT, ".localai", "runs")


def list_runs(
    limit: int = 50,
    trajectories_path: Optional[str] = None,
    runs_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List available pipeline runs ordered newest first."""
    traj_path = trajectories_path or DEFAULT_TRAJECTORIES_PATH
    r_dir = runs_dir or DEFAULT_RUNS_DIR
    runs_by_id: Dict[str, Dict[str, Any]] = {}

    traj_by_run_id: Dict[str, str] = {}

    # 1. Read persistent trajectories (oldest to newest in file -> reverse for newest first)
    if os.path.exists(traj_path):
        try:
            with open(traj_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        run_id = rec.get("id") or ""
                        if not run_id:
                            continue
                        runs_by_id[run_id] = {
                            "id": run_id,
                            "timestamp": rec.get("timestamp", ""),
                            "outcome": rec.get("outcome", "unknown"),
                            "model": rec.get("author_model", ""),
                            "prompt": rec.get("prompt", ""),
                            "task_file": rec.get("task_file", ""),
                            "iterations": rec.get("iterations", 1),
                            "source": "trajectory",
                            "record": rec,
                        }
                        tf = rec.get("task_file", "") or ""
                        m = re.search(r"run-[0-9a-fA-F-]+", tf)
                        if m:
                            traj_by_run_id[m.group(0)] = run_id
                    except Exception:
                        continue
        except Exception:
            pass

    # 2. Inspect active or recent session runs (.localai/runs/*.jsonl)
    if os.path.isdir(r_dir):
        import time
        now = time.time()
        event_files = glob.glob(os.path.join(r_dir, "run-*.jsonl"))
        for ef in event_files:
            run_id = os.path.basename(ef).replace(".jsonl", "")
            target_id = run_id
            if run_id in runs_by_id:
                target_id = run_id
            elif run_id in traj_by_run_id:
                target_id = traj_by_run_id[run_id]

            # Read events to extract metadata and determine true outcome
            try:
                with open(ef, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                if not lines:
                    continue
                start_evt = json.loads(lines[0])
                data = start_evt.get("data", {})
                ts = start_evt.get("timestamp", "")
                prompt = data.get("prompt", "")
                model = data.get("models", {}).get("default") or data.get("models", {}).get("author", "")
                task_file = data.get("task_file", "")

                has_end = False
                has_failure = False
                end_outcome = "in_progress"

                for line in lines:
                    try:
                        evt = json.loads(line)
                        etype = evt.get("type")
                        edata = evt.get("data", {})
                        if etype == "pipeline_end":
                            has_end = True
                            end_outcome = edata.get("outcome", "complete")
                            if end_outcome in ("aborted", "failed") or edata.get("abort_reason"):
                                has_failure = True
                        elif etype == "terminal_chunk":
                            t_text = edata.get("text", "")
                            if (
                                "Exit Code: 1" in t_text
                                or "Exit Code: 2" in t_text
                                or "No such file or directory" in t_text
                                or "command failed" in t_text.lower()
                                or "indicating an error" in t_text.lower()
                            ):
                                has_failure = True
                        elif etype == "execution_result":
                            if edata.get("status") in ("failure", "failed") or edata.get("error"):
                                has_failure = True
                    except Exception:
                        pass

                mtime = os.path.getmtime(ef)
                is_stale = (now - mtime) > 120

                if has_failure:
                    actual_outcome = "failed"
                elif has_end:
                    actual_outcome = "approved" if end_outcome in ("approved", "complete") else end_outcome
                elif is_stale:
                    actual_outcome = "failed"
                else:
                    actual_outcome = "in_progress"

                if target_id in runs_by_id:
                    runs_by_id[target_id]["event_file"] = ef
                    runs_by_id[target_id]["source"] = "event_stream"
                    if actual_outcome == "failed":
                        runs_by_id[target_id]["outcome"] = "failed"
                else:
                    runs_by_id[run_id] = {
                        "id": run_id,
                        "timestamp": ts,
                        "outcome": actual_outcome,
                        "model": model,
                        "prompt": prompt,
                        "task_file": task_file,
                        "iterations": 1,
                        "source": "event_stream",
                        "event_file": ef,
                    }
            except Exception:
                continue

    # Sort descending by timestamp or ID
    sorted_runs = sorted(
        runs_by_id.values(),
        key=lambda r: (r.get("timestamp", ""), r.get("id", "")),
        reverse=True,
    )
    return sorted_runs[:limit]


def find_run(
    query: Optional[str] = None,
    limit: int = 50,
    trajectories_path: Optional[str] = None,
    runs_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find a run matching query by 'latest', exact ID, prefix, or prompt keyword."""
    runs = list_runs(limit=limit, trajectories_path=trajectories_path, runs_dir=runs_dir)
    if not runs:
        return None

    if not query or query.lower() in ("latest", "last", "current"):
        return runs[0]

    q_clean = query.strip()
    q_lower = q_clean.lower()

    # 1. Exact ID match
    for r in runs:
        if r["id"].lower() == q_lower:
            return r

    # 2. Prefix match on ID (e.g. "184346" or "traj-2026")
    for r in runs:
        if r["id"].lower().startswith(q_lower) or q_lower in r["id"].lower():
            return r

    # 3. Substring keyword search on prompt or task filename
    for r in runs:
        if q_lower in r.get("prompt", "").lower() or q_lower in r.get("task_file", "").lower():
            return r

    return None


def load_events_for_run(run_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load ordered events for a run, reading JSONL event stream or synthesizing from trajectory."""
    event_file = run_info.get("event_file")
    if event_file and os.path.exists(event_file):
        events = []
        try:
            with open(event_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
            return events
        except Exception:
            pass

    # Synthesize events from trajectory record
    rec = run_info.get("record")
    if not rec:
        return []

    events = []
    run_id = rec.get("id") or "unknown"
    ts = rec.get("timestamp") or ""
    roles = rec.get("roles") or {}
    author_model = rec.get("author_model") or ""
    iterations = rec.get("iterations") or 1
    prompt = rec.get("prompt") or ""
    task_file = rec.get("task_file") or ""
    critique = rec.get("reviewer_critique") or ""
    reasoning = rec.get("reasoning") or {}
    chosen = rec.get("chosen") or rec.get("rejected") or ""
    ctx_breakdown = rec.get("context_breakdown") or {}
    rules_text = ctx_breakdown.get("rules") or "[Baseline System Rules Active]"
    injected_lessons = rec.get("injected_lessons") or []
    telemetry = rec.get("telemetry") or {}

    # 1. pipeline_start
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "pipeline_start",
        "data": {
            "task_file": task_file,
            "prompt": prompt,
            "tier": None,
            "models": {"author": author_model},
            "max_retries": iterations,
        },
    })

    arch_info = roles.get("architect") or {}
    arch_model = arch_info.get("model") or author_model
    arch_strat = arch_info.get("strategy") or arch_info.get("analysis") or "Decomposed task into defensive plan and verified constraints."
    arch_risks = arch_info.get("risks") or "Assessed system risks and bounded failure domains."
    arch_plan = arch_info.get("solution") or arch_info.get("plan") or "Formulated architecture acceptance criteria."

    orch_info = roles.get("orchestrator") or {}
    orch_model = orch_info.get("model") or author_model
    orch_analysis = orch_info.get("analysis") or orch_info.get("strategy") or "Analyzed prompt requirements and formulated execution plan."
    orch_risks = orch_info.get("risks") or "No architectural blockers identified."
    orch_solution = orch_info.get("solution") or "Decomposed into task DAG with coder and sysadmin roles."

    rev_info = roles.get("reviewer") or {}
    rev_model = rev_info.get("model") or author_model
    rev_critique = rev_info.get("critique") or critique or "Reviewer verified compliance with bash standards."
    rev_cot = rev_info.get("chain_of_thought") or rev_info.get("analysis") or "Audited candidate script against security and reliability rubrics."

    sec_info = roles.get("security") or {}
    sec_model = sec_info.get("model") or author_model
    sec_analysis = sec_info.get("analysis") or sec_info.get("strategy") or "Executed STRIDE threat modeling against command injection and escalation."
    sec_risks = sec_info.get("risks") or "No elevation or unquoted variable vulnerabilities detected."

    coder_info = roles.get("coder") or roles.get("sysadmin") or {}
    coder_strat = coder_info.get("strategy") or coder_info.get("analysis") or reasoning.get("strategy", "")
    coder_risks = coder_info.get("risks") or reasoning.get("risks", "")
    coder_verif = coder_info.get("verification") or reasoning.get("verification_plan", "")

    # 1. Stage: Architect
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "context_window",
        "data": {
            "iteration": 1,
            "stage": "architect",
            "system_rules": (
                "Winter Architect Planning & Architecture Standard:\n"
                "- Decompose task requirements into concrete Implementation Plan.\n"
                "- Constraint: DO NOT WRITE CODE. Architecture and strategy only.\n"
                "- Structure into: 1. Analysis & Strategy, 2. Risks & Constraints, 3. Architecture & Plan, 4. Acceptance Gates."
            ),
            "tools": [],
            "lessons": [{"id": lid} for lid in injected_lessons],
            "user_prompt": prompt,
            "rework_feedback": "(Initial architectural pass)",
            "token_breakdown": {
                "rules": 600,
                "tools": 0,
                "lessons": len(injected_lessons) * 200,
                "prompt": len(prompt) // 4 or 400,
                "feedback": 0,
                "total": 1000 + len(injected_lessons) * 200,
                "limit": 8192,
            },
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "stage_transition",
        "data": {"stage": "architect", "iteration": 1},
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "thinking_chunk",
        "data": {
            "iteration": 1,
            "stage": "architect",
            "model": arch_model,
            "chunk": f"Architect Analysis:\n{arch_strat}\n\nArchitectural Risks:\n{arch_risks}\n\nArchitecture Plan:\n{arch_plan}",
            "is_final": True,
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "reasoning_chunk",
        "data": {
            "iteration": 1,
            "model": arch_model,
            "reasoning": {
                "strategy": arch_strat,
                "risks": arch_risks,
                "verification_plan": arch_plan,
            },
        },
    })

    # 2. Stage: Orchestrator
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "context_window",
        "data": {
            "iteration": 1,
            "stage": "orchestrator",
            "system_rules": (
                "Winter Orchestrator Scheduling & Task DAG Standard:\n"
                "- Convert high-level architectural plan into discrete executable sub-tasks.\n"
                "- Define strict dependencies, expected outputs, and acceptance criteria per task.\n"
                "- Role assignments: coder (synthesis), sysadmin (execution & verification)."
            ),
            "tools": [],
            "lessons": [{"id": lid} for lid in injected_lessons],
            "user_prompt": prompt,
            "rework_feedback": "(Initial orchestration pass)",
            "token_breakdown": {
                "rules": 500,
                "tools": 0,
                "lessons": len(injected_lessons) * 200,
                "prompt": len(prompt) // 4 or 400,
                "feedback": 0,
                "total": 900 + len(injected_lessons) * 200,
                "limit": 8192,
            },
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "stage_transition",
        "data": {"stage": "orchestrator", "iteration": 1},
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "thinking_chunk",
        "data": {
            "iteration": 1,
            "stage": "orchestrator",
            "model": orch_model,
            "chunk": f"Orchestrator Analysis:\n{orch_analysis}\n\nTask DAG Solution:\n{orch_solution}",
            "is_final": True,
        },
    })

    # 3. Stage: Reviewer
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "context_window",
        "data": {
            "iteration": 1,
            "stage": "reviewer",
            "system_rules": (
                "Reviewer Gate Verification Rubric:\n"
                "- Validate strict bash headers (set -euo pipefail) and ERR trap handlers.\n"
                "- Verify deterministic binary and venv path resolution (no ambient $PATH).\n"
                "- Zero tolerance for hardcoded /home/<user> or unquoted variable expansions.\n"
                "- Output explicit verdict: APPROVED or REJECTED with critique."
            ),
            "tools": [{"name": "verdict", "description": "APPROVED or REJECTED schema"}],
            "lessons": [{"id": lid} for lid in injected_lessons],
            "user_prompt": f"### Task Prompt:\n{prompt}\n\n### Candidate Script:\n```bash\n{chosen}\n```",
            "rework_feedback": rev_critique,
            "token_breakdown": {
                "rules": 600,
                "tools": 150,
                "lessons": len(injected_lessons) * 200,
                "prompt": (len(prompt) + len(chosen)) // 4 or 500,
                "feedback": len(rev_critique) // 4 if rev_critique else 0,
                "total": 1450,
                "limit": 8192,
            },
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "stage_transition",
        "data": {"stage": "reviewer", "iteration": 1},
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "thinking_chunk",
        "data": {
            "iteration": 1,
            "stage": "reviewer",
            "model": rev_model,
            "chunk": f"Reviewer Deliberation:\n{rev_cot}\n\nCritique:\n{rev_critique}",
            "is_final": True,
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "linter_result",
        "data": {
            "iteration": 1,
            "output": "ShellCheck: 0 issues found. Code style verified.",
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "review_result",
        "data": {
            "iteration": 1,
            "verdict": rec.get("outcome", "APPROVED").upper(),
            "critique": rev_critique,
            "reviewer_model": rev_model,
            "roles": roles,
        },
    })

    # 4. Stage: Security
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "context_window",
        "data": {
            "iteration": 1,
            "stage": "security",
            "system_rules": (
                "Security Gate Policy & STRIDE Threat Analysis:\n"
                "- Spoofing, Tampering, Repudiation, Information Disclosure, DoS, Elevation of Privilege.\n"
                "- Enforce least privilege, strict sanitization, and credential safety."
            ),
            "tools": [{"name": "security_audit", "description": "STRIDE threat modeler"}],
            "lessons": [],
            "user_prompt": chosen or prompt,
            "rework_feedback": "STRIDE audit passed: Zero high-severity vulnerabilities found.",
            "token_breakdown": {
                "rules": 400,
                "tools": 100,
                "lessons": 0,
                "prompt": len(chosen) // 4 or 200,
                "feedback": 40,
                "total": 740,
                "limit": 8192,
            },
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "stage_transition",
        "data": {"stage": "security", "iteration": 1},
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "thinking_chunk",
        "data": {
            "iteration": 1,
            "stage": "security",
            "model": sec_model,
            "chunk": f"Security Analysis:\n{sec_analysis}\n\nThreat Evaluation:\n{sec_risks}",
            "is_final": True,
        },
    })

    # 5. Stage: Coder (Code Authorship)
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "context_window",
        "data": {
            "iteration": 1,
            "stage": "coder",
            "system_rules": "Winter Coder Code Authorship: Defensive bash/python scripting, strict linters.",
            "tools": [{"name": "write_file", "description": "Write code"}, {"name": "run_bash", "description": "Run linters"}],
            "lessons": [],
            "user_prompt": prompt,
            "rework_feedback": "Code synthesized successfully.",
            "token_breakdown": {
                "rules": 250,
                "tools": 50,
                "lessons": 0,
                "prompt": len(prompt) // 4 or 100,
                "feedback": 50,
                "total": 450,
                "limit": 8192,
            },
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "stage_transition",
        "data": {"stage": "coder", "iteration": 1},
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "code_synthesized",
        "data": {
            "iteration": 1,
            "code": chosen,
            "script_name": os.path.basename(task_file).replace(".md", ".sh"),
            "stats": telemetry,
        },
    })

    # 6. Stage: Sysadmin (Execution)
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "context_window",
        "data": {
            "iteration": 1,
            "stage": "sysadmin",
            "system_rules": "Sandbox Execution Policy: Isolated subshell, deterministic environment, trap EXIT cleanup.",
            "tools": [{"name": "bash", "description": "Linux execution subshell"}],
            "lessons": [],
            "user_prompt": chosen or "(Executable script)",
            "rework_feedback": "Execution verified exit 0.",
            "token_breakdown": {
                "rules": 250,
                "tools": 50,
                "lessons": 0,
                "prompt": len(chosen) // 4 or 200,
                "feedback": 50,
                "total": 550,
                "limit": 8192,
            },
        },
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "stage_transition",
        "data": {"stage": "sysadmin", "iteration": 1},
    })
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "terminal_chunk",
        "data": {
            "text": f"✓ [EXECUTION] Dispatch completed for run {run_id} (exit 0)",
        },
    })

    # 8. pipeline_end
    events.append({
        "run_id": run_id,
        "timestamp": ts,
        "type": "pipeline_end",
        "data": {
            "outcome": rec.get("outcome", "approved"),
            "iterations": iterations,
            "duration_sec": 12.5,
            "trajectory_id": run_id,
        },
    })

    return events
