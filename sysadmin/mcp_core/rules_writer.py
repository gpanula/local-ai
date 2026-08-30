"""Markdown writer for the universal system rules store (Phase 6.02).

Appends a promoted universal rule to ``sysadmin/prompts/SYSTEM_RULES.md`` with
provenance metadata and auto-incremented ``### Rule #N`` numbering. Pure file
I/O — no database access, no Ollama calls.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any, List


def _derive_title(rule_text: str, max_len: int = 60) -> str:
    """Derive a short title from the first line of the rule text."""
    first_line = (rule_text or "").strip().splitlines()[0] if (rule_text or "").strip() else ""
    # Strip leading markdown bullets / numbering.
    cleaned = re.sub(r"^[\s\-*#\d\.]+", "", first_line).strip()
    if not cleaned:
        cleaned = "Universal Rule"
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


def _next_rule_number(content: str) -> int:
    """Return the next rule number based on existing ``### Rule #N`` headers."""
    numbers = [int(m) for m in re.findall(r"^###\s*Rule\s*#(\d+)", content, flags=re.MULTILINE)]
    return (max(numbers) + 1) if numbers else 1


def _format_rule_block(rule_text: str, source_lesson_ids: List[str], rule_number: int) -> str:
    """Render a single rule as a numbered markdown block with provenance."""
    title = _derive_title(rule_text)
    promoted = date.today().isoformat()
    sources = ", ".join(str(s) for s in source_lesson_ids) if source_lesson_ids else "—"
    lines = [
        f"### Rule #{rule_number}: {title}",
        f"**Promoted**: {promoted} | **Source Lessons**: {sources}",
        "",
        rule_text.strip(),
    ]
    return "\n".join(lines)


def append_system_rule(
    rule_text: str,
    source_lesson_ids: List[str],
    rules_md_path: str,
) -> None:
    """Append a promoted universal rule to ``SYSTEM_RULES.md``.

    Auto-increments the rule number based on existing ``### Rule #N`` headers,
    includes provenance (promotion date + source lesson IDs), and appends below
    the existing content without overwriting prior rules. Creates the file if it
    does not exist.
    """
    parent = os.path.dirname(rules_md_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    existing = ""
    if os.path.exists(rules_md_path):
        with open(rules_md_path, "r", encoding="utf-8") as f:
            existing = f.read()

    rule_number = _next_rule_number(existing)
    block = _format_rule_block(rule_text, source_lesson_ids, rule_number)

    # Ensure a blank line separates the new block from any prior content.
    separator = "\n" if existing and not existing.endswith("\n\n") else ""
    with open(rules_md_path, "a", encoding="utf-8") as f:
        f.write(f"{separator}{block}\n")
