"""Trajectory recording for future fine-tuning data (Phase 7.01/7.02).

Records rejected/approved script pairs from multi-iteration pipeline runs as
JSONL lines in ``sysadmin/data/trajectories.jsonl``. Uses a tiered schema to
prevent bloat: small scripts (<150 lines) store ``rejected``/``chosen`` inline;
large scripts (>=150 lines) store a unified ``diff`` + ``focused_snippet`` inline
and offload the verbatim files to ``sysadmin/data/raw_trajectories/<id>/``.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from mcp_core.audit import normalize_category
from mcp_core.workspace import WORKSPACE_ROOT

# Default trajectory store (relative to workspace root).
DEFAULT_TRAJECTORIES_PATH = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "trajectories.jsonl")

# Default raw-file offload directory (relative to workspace root).
DEFAULT_RAW_DIR = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "raw_trajectories")

# Scripts at or above this many lines use the diff+ref tier.
TIER2_LINE_THRESHOLD = 150

# Number of lines around the failure point to include in the focused snippet.
FOCUSED_SNIPPET_RADIUS = 15

# Stop-words filtered out of reviewer-critique keyword extraction.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "that", "this", "is", "are", "was", "were", "be", "been", "it", "as",
    "at", "by", "from", "your", "you", "must", "should", "not", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "fix",
    "fixes", "issue", "issues", "error", "errors", "please", "script",
}


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _new_trajectory_id() -> str:
    """Generate a unique trajectory ID."""
    return f"traj-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _critique_keywords(critique: str) -> set:
    """Derive significant keyword tokens from the reviewer critique."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", (critique or "").lower())
    return {tok for tok in tokens if tok not in _STOPWORDS}


def _focused_snippet(chosen: str, critique: str, radius: int = FOCUSED_SNIPPET_RADIUS) -> str:
    """Return ±``radius`` lines of ``chosen`` around the first critique-keyword match."""
    lines = (chosen or "").splitlines()
    if not lines:
        return ""
    keywords = _critique_keywords(critique)
    anchor = 0
    if keywords:
        for idx, line in enumerate(lines):
            if any(kw in line.lower() for kw in keywords):
                anchor = idx
                break
    start = max(0, anchor - radius)
    end = min(len(lines), anchor + radius + 1)
    return "\n".join(lines[start:end])


def _unified_diff(rejected: str, chosen: str) -> str:
    """Return a unified diff between the rejected and chosen script versions."""
    diff = difflib.unified_diff(
        (rejected or "").splitlines(),
        (chosen or "").splitlines(),
        fromfile="rejected",
        tofile="chosen",
        lineterm="",
    )
    return "\n".join(diff)


def _write_raw_files(trajectory_id: str, rejected: str, chosen: str, raw_dir: str) -> str:
    """Write verbatim script files to ``raw_dir/<id>/`` and return the relative dir."""
    subdir = os.path.join(raw_dir, trajectory_id)
    os.makedirs(subdir, exist_ok=True)
    with open(os.path.join(subdir, "rejected.sh"), "w", encoding="utf-8") as f:
        f.write(rejected or "")
    with open(os.path.join(subdir, "chosen.sh"), "w", encoding="utf-8") as f:
        f.write(chosen or "")
    # Return a workspace-relative path for portability.
    return os.path.relpath(subdir, WORKSPACE_ROOT)


def _build_record(
    pipeline_result: dict,
    prompt_content: str,
    task_file: str,
    raw_dir: str,
) -> dict:
    """Assemble the trajectory record dict with tiered payload logic."""
    script_versions = pipeline_result.get("script_versions", []) or []
    chosen = script_versions[-1] if script_versions else pipeline_result.get("final_code_block", "")
    rejected = script_versions[-2] if len(script_versions) >= 2 else ""

    iterations = int(pipeline_result.get("iterations", 0))
    approved = bool(pipeline_result.get("approved", False))
    abort_reason = pipeline_result.get("abort_reason", "")
    if abort_reason:
        outcome = "aborted"
    elif approved:
        outcome = "approved"
    else:
        outcome = "failed"

    reasoning = pipeline_result.get("reasoning") or {}
    roles = pipeline_result.get("roles") or {}
    # Ensure coder reasoning is represented in roles["coder"]
    if "coder" not in roles and reasoning:
        roles["coder"] = {
            "model": pipeline_result.get("author_model", ""),
            "strategy": reasoning.get("strategy", ""),
            "risks": reasoning.get("risks", ""),
            "solution": chosen or rejected or "",
            "verification": reasoning.get("verification_plan", ""),
        }

    raw_category = pipeline_result.get("category", "")
    keywords = pipeline_result.get("keywords", [])
    if not keywords and prompt_content:
        words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", prompt_content)
        keywords = [w.lower() for w in words if w.lower() not in _STOPWORDS][:10]
    canonical_category = normalize_category(keywords, raw_category)

    record: Dict[str, Any] = {
        "id": _new_trajectory_id(),
        "timestamp": _now_iso(),
        "task_file": task_file,
        "canonical_category": canonical_category,
        "prompt": prompt_content,
        "author_model": pipeline_result.get("author_model", ""),
        "injected_lessons": pipeline_result.get("injected_lessons", []),
        "reviewer_critique": pipeline_result.get("last_critique", ""),
        "reasoning": reasoning,
        "roles": roles,
        "telemetry": pipeline_result.get("author_stats", {}),
        "iterations": iterations,
        "outcome": outcome,
        "payload_type": None,
        "rejected": None,
        "chosen": None,
        "diff": None,
        "focused_snippet": None,
        "raw_dir": None,
    }

    chosen_line_count = len((chosen or "").splitlines())
    if chosen_line_count < TIER2_LINE_THRESHOLD:
        # Tier 1: inline.
        record["payload_type"] = "inline"
        record["rejected"] = rejected
        record["chosen"] = chosen
    else:
        # Tier 2: diff + focused snippet inline, verbatim files offloaded.
        record["payload_type"] = "diff_and_ref"
        record["diff"] = _unified_diff(rejected, chosen)
        record["focused_snippet"] = _focused_snippet(chosen, record["reviewer_critique"])
        record["raw_dir"] = _write_raw_files(record["id"], rejected, chosen, raw_dir)

    return record


def record_trajectory(
    pipeline_result: dict,
    prompt_content: str,
    trajectories_path: Optional[str] = None,
    raw_dir: Optional[str] = None,
    task_file: str = "",
) -> str:
    """Append a single JSON line to the trajectory store and return the record ID.

    Only meaningful for multi-iteration runs (``iterations > 1``); callers should
    gate on that. Appends one JSON object per line (JSONL). Creates the parent
    directory if needed. Returns the generated trajectory ID.
    """
    path = trajectories_path or DEFAULT_TRAJECTORIES_PATH
    raw = raw_dir or DEFAULT_RAW_DIR

    record = _build_record(pipeline_result, prompt_content, task_file, raw)

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record["id"]
