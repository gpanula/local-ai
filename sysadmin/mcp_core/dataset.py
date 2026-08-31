"""Dataset export utilities for fine-tuning Local AI models (SFT & DPO).

Converts multi-iteration trajectory records from ``sysadmin/data/trajectories.jsonl``
into industry-standard training formats for local fine-tuning frameworks (Unsloth,
TRL, Axolotl, Llama-Factory):
1. **DPO (Direct Preference Optimization)**: ``prompt``, ``chosen``, ``rejected`` pairs.
2. **SFT Multi-Turn (Self-Correction)**: User task -> Rejected script -> Reviewer feedback -> Chosen script.
3. **SFT Direct (Instruction Tuning)**: User task -> Chosen script.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from mcp_core.workspace import WORKSPACE_ROOT

DEFAULT_TRAJECTORIES_PATH = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "trajectories.jsonl")
DEFAULT_DATASET_OUTPUT_DIR = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "training")

_DEFAULT_SYSTEM_PROMPT = (
    "You are a defensive systems and automation engineer. Generate robust, standalone, "
    "and highly portable Bash scripts that strictly adhere to repo defensive rules, "
    "deterministic environment resolution, binary isolation, and zero ShellCheck errors."
)


def load_trajectories(trajectories_path: Optional[str] = None) -> List[dict]:
    """Load all trajectory records from a JSONL file."""
    path = trajectories_path or DEFAULT_TRAJECTORIES_PATH
    if not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def resolve_trajectory_code(record: dict) -> Tuple[str, str]:
    """Resolve (rejected, chosen) code strings whether inline or offloaded to raw_dir."""
    rejected = record.get("rejected") or ""
    chosen = record.get("chosen") or ""

    # If already populated inline, return immediately
    if rejected and chosen:
        return rejected, chosen

    # Check raw_dir if available
    raw_dir = record.get("raw_dir")
    if raw_dir and os.path.isdir(raw_dir):
        rej_file = os.path.join(raw_dir, "rejected.sh")
        cho_file = os.path.join(raw_dir, "chosen.sh")
        if os.path.exists(rej_file) and not rejected:
            try:
                with open(rej_file, "r", encoding="utf-8") as f:
                    rejected = f.read()
            except Exception:
                pass
        if os.path.exists(cho_file) and not chosen:
            try:
                with open(cho_file, "r", encoding="utf-8") as f:
                    chosen = f.read()
            except Exception:
                pass

    return rejected, chosen


def _build_task_prompt(record: dict) -> str:
    """Reconstruct task prompt with injected lessons if present."""
    task_file = record.get("task_file", "")
    injected_lessons = record.get("injected_lessons", []) or []

    prompt_parts = []
    if task_file:
        prompt_parts.append(f"### Target Task File: {task_file}")
    if injected_lessons:
        rules_text = "\n".join(f"- {rule}" for rule in injected_lessons)
        prompt_parts.append(f"### Applicable System Rules:\n{rules_text}")

    prompt_parts.append("Please author the implementation script adhering to all defensive standards.")
    return "\n\n".join(prompt_parts)


def export_dpo_records(records: List[dict], approved_only: bool = True) -> List[dict]:
    """Convert trajectory records to standard DPO prompt/chosen/rejected triplets."""
    dpo_items = []
    for r in records:
        if approved_only and r.get("outcome") != "approved":
            continue

        rejected, chosen = resolve_trajectory_code(r)
        if not rejected or not chosen or rejected.strip() == chosen.strip():
            continue

        prompt = _build_task_prompt(r)
        dpo_items.append({
            "id": r.get("id", ""),
            "prompt": prompt,
            "chosen": chosen.strip(),
            "rejected": rejected.strip(),
            "critique": r.get("reviewer_critique", ""),
            "task_file": r.get("task_file", ""),
            "iterations": r.get("iterations", 1),
        })
    return dpo_items


def export_sft_multiturn_records(records: List[dict], approved_only: bool = True) -> List[dict]:
    """Convert trajectory records to multi-turn self-correction conversation turns."""
    sft_items = []
    for r in records:
        if approved_only and r.get("outcome") != "approved":
            continue

        rejected, chosen = resolve_trajectory_code(r)
        if not rejected or not chosen or rejected.strip() == chosen.strip():
            continue

        critique = r.get("reviewer_critique", "Pre-flight linter findings detected syntax or defensive violations.")
        user_prompt = _build_task_prompt(r)

        messages = [
            {"role": "system", "content": _DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": rejected.strip()},
            {"role": "user", "content": f"### Reviewer / Linter Findings:\n{critique}\n\nPlease fix all findings and output the clean, defensive script."},
            {"role": "assistant", "content": chosen.strip()},
        ]
        sft_items.append({
            "id": r.get("id", ""),
            "messages": messages,
            "task_file": r.get("task_file", ""),
        })
    return sft_items


def synthesize_lesson_contrastive_pairs() -> List[dict]:
    """Generate high-quality contrastive (prompt, rejected, chosen) triplets directly derived from lessons.md invariants."""
    return [
        {
            "id": "synthetic-lesson-sc2034-unused-var",
            "category": "Defensive Bash",
            "prompt": "Synthesize a standalone script that outputs the system hostname.",
            "rejected": "#!/bin/bash\nset -euo pipefail\ncontext_length=16384\nprocessor=\"gpu\"\nhostname\n",
            "chosen": "#!/bin/bash\nset -euo pipefail\nhostname\n",
            "explanation": "Removed unused scaffolding variables context_length and processor that triggered ShellCheck SC2034.",
        },
        {
            "id": "synthetic-lesson-binary-isolation",
            "prompt": "Synthesize a standalone script to execute unit tests using the repository pytest tool.",
            "category": "Binary Isolation",
            "rejected": "#!/bin/bash\nset -euo pipefail\npytest sysadmin/tests/ -q\n",
            "chosen": "#!/bin/bash\nset -euo pipefail\nREPO_ROOT=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")/..\" && pwd -P)\"\nVENV_DIR=\"${1:-${REPO_ROOT}/sysadmin/venv}\"\nif [ ! -x \"${VENV_DIR}/bin/pytest\" ]; then\n    echo \"❌ [ERROR] pytest binary not found in isolated venv: ${VENV_DIR}\" >&2\n    exit 1\nfi\n\"${VENV_DIR}/bin/pytest\" sysadmin/tests/ -q\n",
            "explanation": "Avoided relying on ambient $PATH; deterministically resolved isolated venv and asserted binary executable.",
        },
        {
            "id": "synthetic-lesson-sc2154-heredoc-quotes",
            "category": "ShellCheck",
            "prompt": "Synthesize a bash test fixture that generates a mock shell script containing runtime variables.",
            "rejected": "#!/bin/bash\nset -euo pipefail\ncat > /tmp/fixture.sh <<EOF\necho \"Target: \\$TARGET_VAR\"\nEOF\n",
            "chosen": "#!/bin/bash\nset -euo pipefail\ncat > /tmp/fixture.sh <<'EOF'\necho \"Target: ${TARGET_VAR}\"\nEOF\n",
            "explanation": "Quoted heredoc delimiter <<'EOF' to prevent premature expansion and ShellCheck SC2154 warnings.",
        },
        {
            "id": "synthetic-lesson-sc2028-echo-newlines",
            "category": "ShellCheck",
            "prompt": "Synthesize a script that prints a multi-line deployment banner.",
            "rejected": "#!/bin/bash\nset -euo pipefail\necho \"=== SYSTEM START ===\\nStarting deployment...\"\n",
            "chosen": "#!/bin/bash\nset -euo pipefail\nprintf \"=== SYSTEM START ===\\nStarting deployment...\\n\"\n",
            "explanation": "Replaced echo with escape sequences (SC2028) with printf for POSIX/Bash compatibility.",
        },
        {
            "id": "synthetic-lesson-ansible-fqcn",
            "category": "Ansible",
            "prompt": "Synthesize an Ansible playbook to check host connectivity.",
            "rejected": "---\n- hosts: all\n  tasks:\n    - ping:\n",
            "chosen": "---\n- name: Verify host connectivity\n  hosts: all\n  gather_facts: false\n  tasks:\n    - name: Ping host\n      ansible.builtin.ping:\n",
            "explanation": "Added explicit task names and Fully Qualified Collection Names (FQCN) with trailing colon mapping.",
        },
        {
            "id": "synthetic-lesson-python-clean-types",
            "category": "Python Quality",
            "prompt": "Synthesize a Python utility function to load and parse a JSON configuration file safely.",
            "rejected": "import os, sys, json\n\ndef load_config(path):\n    temp = None\n    f = open(path)\n    data = json.load(f)\n    return data\n",
            "chosen": "import json\nfrom pathlib import Path\nfrom typing import Any, Dict\n\ndef load_config(config_path: Path) -> Dict[str, Any]:\n    \"\"\"Load and parse JSON configuration file.\"\"\"\n    return json.loads(config_path.read_text(encoding=\"utf-8\"))\n",
            "explanation": "Used modern Pathlib, type annotations, context manager/read_text, and removed unused symbols.",
        },
    ]


def export_sft_direct_records(records: List[dict], approved_only: bool = True) -> List[dict]:
    """Convert trajectory records to single-turn direct instruction-tuning examples."""
    sft_items = []
    for r in records:
        if approved_only and r.get("outcome") != "approved":
            continue

        _, chosen = resolve_trajectory_code(r)
        if not chosen:
            continue

        user_prompt = _build_task_prompt(r)
        messages = [
            {"role": "system", "content": _DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": chosen.strip()},
        ]
        sft_items.append({
            "id": r.get("id", ""),
            "messages": messages,
            "task_file": r.get("task_file", ""),
        })
    return sft_items


def export_datasets(
    trajectories_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    formats: Optional[List[str]] = None,
    approved_only: bool = True,
    include_synthetic_lessons: bool = False,
    role: Optional[str] = None,
) -> Dict[str, int]:
    """Export trajectories and synthetic lesson exemplars to formatted JSONL datasets.

    Returns a dict mapping format name to exported sample count.
    """
    out_dir = output_dir or DEFAULT_DATASET_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    records = load_trajectories(trajectories_path)
    selected_formats = formats or ["dpo", "sft_multiturn", "sft_direct"]
    counts = {}

    # Gather synthetic lesson pairs
    synth_pairs = synthesize_lesson_contrastive_pairs() if include_synthetic_lessons else []

    if "dpo" in selected_formats or "all" in selected_formats:
        dpo_data = export_dpo_records(records, approved_only=approved_only)
        for s in synth_pairs:
            dpo_data.append({
                "id": s["id"],
                "prompt": f"### Applicable System Rules:\n- {s.get('category', 'Defensive Standard')}\n\nTask: {s['prompt']}\n\nPlease author the implementation script adhering to all defensive standards.",
                "chosen": s["chosen"].strip(),
                "rejected": s["rejected"].strip(),
                "critique": s.get("explanation", ""),
                "task_file": "",
                "iterations": 2,
            })
        dpo_path = os.path.join(out_dir, "dpo_dataset.jsonl")
        with open(dpo_path, "w", encoding="utf-8") as f:
            for item in dpo_data:
                f.write(json.dumps(item) + "\n")
        counts["dpo"] = len(dpo_data)

    if "sft_multiturn" in selected_formats or "all" in selected_formats:
        sft_multi = export_sft_multiturn_records(records, approved_only=approved_only)
        for s in synth_pairs:
            sft_multi.append({
                "id": s["id"],
                "messages": [
                    {"role": "system", "content": _DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": s["prompt"]},
                    {"role": "assistant", "content": s["rejected"].strip()},
                    {"role": "user", "content": f"Feedback: {s['explanation']}. Please correct the implementation adhering to defensive standards."},
                    {"role": "assistant", "content": s["chosen"].strip()},
                ],
                "task_file": "",
            })
        sft_multi_path = os.path.join(out_dir, "sft_multiturn_dataset.jsonl")
        with open(sft_multi_path, "w", encoding="utf-8") as f:
            for item in sft_multi:
                f.write(json.dumps(item) + "\n")
        counts["sft_multiturn"] = len(sft_multi)

    if "sft_direct" in selected_formats or "all" in selected_formats:
        sft_direct = export_sft_direct_records(records, approved_only=approved_only)
        for s in synth_pairs:
            sft_direct.append({
                "id": s["id"],
                "messages": [
                    {"role": "system", "content": _DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": s["prompt"]},
                    {"role": "assistant", "content": s["chosen"].strip()},
                ],
                "task_file": "",
            })
        sft_direct_path = os.path.join(out_dir, "sft_direct_dataset.jsonl")
        with open(sft_direct_path, "w", encoding="utf-8") as f:
            for item in sft_direct:
                f.write(json.dumps(item) + "\n")
        counts["sft_direct"] = len(sft_direct)

    return counts
