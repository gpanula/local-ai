"""Wiki generators for the memory-health dashboard (Phase 7.03/7.04).

Produces Obsidian-friendly markdown files under ``ollama_update/wiki/``:
``index.md`` (categorized lesson catalog), ``dashboard.md`` (telemetry snapshot),
and ``log.md`` (append-only chronological event log). Pure file I/O — no database
access, no Ollama calls.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from mcp_core.audit import cluster_lessons, flag_low_utility


def _format_keywords(keywords) -> str:
    """Render a keywords value (list or string) as a comma-joined string."""
    if isinstance(keywords, str):
        try:
            parsed = json.loads(keywords)
            if isinstance(parsed, list):
                keywords = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if isinstance(keywords, (list, tuple)):
        return ", ".join(str(k) for k in keywords)
    return str(keywords or "")


def _truncate(text: str, max_len: int = 60) -> str:
    """Truncate text to ``max_len`` chars with an ellipsis."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _utility_score(lesson: dict) -> float:
    """Reuse the Phase 5 utility multiplier ``(prevented+1)/(retrieved+2)``."""
    retrieved = int(lesson.get("retrieval_count", 0))
    prevented = int(lesson.get("prevented_rework_count", 0))
    return (prevented + 1) / (retrieved + 2)


def _ensure_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def generate_index(lessons: List[dict], output_path: str) -> None:
    """Generate ``index.md`` — a categorized catalog of all active lessons.

    Groups lessons by category into markdown tables. Each row: lesson ID (as an
    Obsidian ``[[id]]`` link), keywords, rule summary (truncated), source task,
    created date. An empty lesson list produces a valid file with a
    "No lessons recorded" message.
    """
    _ensure_dir(output_path)

    lines = ["# Lesson Index", ""]
    if not lessons:
        lines.append("No lessons recorded.")
        lines.append("")
        _write(output_path, lines)
        return

    # Group by category, preserving first-seen order.
    by_category: Dict[str, List[dict]] = {}
    for lesson in lessons:
        cat = lesson.get("category") or "unknown"
        by_category.setdefault(cat, []).append(lesson)

    for cat, cat_lessons in by_category.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| ID | Keywords | Rule | Source Task | Created |")
        lines.append("|:---|:---|:---|:---|:---|")
        for lesson in cat_lessons:
            lesson_id = lesson.get("id", "")
            lines.append(
                f"| [[{lesson_id}]] | {_format_keywords(lesson.get('keywords', []))} | "
                f"{_truncate(lesson.get('rule', ''))} | "
                f"{lesson.get('source_task', '')} | {lesson.get('created', '')} |"
            )
        lines.append("")

    _write(output_path, lines)


def generate_dashboard(lessons: List[dict], output_path: str) -> None:
    """Generate ``dashboard.md`` — a telemetry snapshot with health indicators.

    Sections: top-retrieved lessons, highest-utility lessons, promotion
    candidates (clusters), and low-utility flags. Includes computed stats
    (retrieval_count, prevention_ratio, utility_score).
    """
    _ensure_dir(output_path)

    lines = ["# Memory Health Dashboard", ""]
    if not lessons:
        lines.append("No lessons recorded.")
        lines.append("")
        _write(output_path, lines)
        return

    # Top-retrieved.
    top_retrieved = sorted(
        lessons, key=lambda l: int(l.get("retrieval_count", 0)), reverse=True
    )[:10]
    lines.append("## Top-Retrieved Lessons")
    lines.append("")
    lines.append("| ID | Retrievals | Prevented | Ineffective | Utility |")
    lines.append("|:---|:---|:---|:---|:---|")
    for lesson in top_retrieved:
        lines.append(
            f"| [[{lesson.get('id', '')}]] | {lesson.get('retrieval_count', 0)} | "
            f"{lesson.get('prevented_rework_count', 0)} | "
            f"{lesson.get('ineffective_count', 0)} | {_utility_score(lesson):.2f} |"
        )
    lines.append("")

    # Highest-utility.
    top_utility = sorted(lessons, key=_utility_score, reverse=True)[:10]
    lines.append("## Highest-Utility Lessons")
    lines.append("")
    lines.append("| ID | Utility | Retrievals | Prevented |")
    lines.append("|:---|:---|:---|:---|")
    for lesson in top_utility:
        lines.append(
            f"| [[{lesson.get('id', '')}]] | {_utility_score(lesson):.2f} | "
            f"{lesson.get('retrieval_count', 0)} | "
            f"{lesson.get('prevented_rework_count', 0)} |"
        )
    lines.append("")

    # Promotion candidates (clusters).
    clusters = cluster_lessons(lessons, min_cluster_size=3)
    lines.append("## Promotion Candidates")
    lines.append("")
    if clusters:
        lines.append("| Cluster | Category | Keywords | Lesson IDs | Count |")
        lines.append("|:---|:---|:---|:---|:---|")
        for cluster in clusters:
            lines.append(
                f"| {cluster['count']} lessons | {cluster['category']} | "
                f"{_format_keywords(cluster['keywords'])} | "
                f"{', '.join(str(i) for i in cluster['lesson_ids'])} | "
                f"{cluster['count']} |"
            )
    else:
        lines.append("No promotion candidates.")
    lines.append("")

    # Low-utility flags.
    low_utility = flag_low_utility(lessons, min_retrievals=5, max_prevention_ratio=0.3)
    lines.append("## Low-Utility Flags")
    lines.append("")
    if low_utility:
        lines.append("| ID | Retrievals | Prevention Ratio | Utility |")
        lines.append("|:---|:---|:---|:---|")
        for lesson in low_utility:
            lines.append(
                f"| [[{lesson.get('id', '')}]] | {lesson.get('retrieval_count', 0)} | "
                f"{lesson.get('prevention_ratio', 0.0):.2f} | "
                f"{lesson.get('utility_score', 0.0):.2f} |"
            )
    else:
        lines.append("No low-utility lessons.")
    lines.append("")

    _write(output_path, lines)


def generate_log(events: List[dict], output_path: str) -> None:
    """Append chronological entries to ``log.md`` (append-only).

    Each event is rendered as a timestamped bullet. Running twice does not
    overwrite prior entries.
    """
    _ensure_dir(output_path)

    if not events:
        return

    with open(output_path, "a", encoding="utf-8") as f:
        for event in events:
            ts = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
            message = event.get("message", "")
            f.write(f"- `{ts}` {message}\n")


def _write(path: str, lines: List[str]) -> None:
    """Write lines to ``path`` (overwrites existing content)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
