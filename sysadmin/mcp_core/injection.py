"""Markdown formatter for injecting relevant lessons into the Author prompt.

Phase 4.01: renders a list of lesson dicts as a human-readable markdown section
suitable for prepending to the Author prompt. Pure function — no database access,
no Ollama calls, no raw JSON in the output.
"""

from __future__ import annotations

from typing import Any


def _format_keywords(keywords: Any) -> str:
    """Render a keywords value (list or string) as a comma-joined string."""
    if isinstance(keywords, str):
        return keywords
    if isinstance(keywords, (list, tuple)):
        return ", ".join(str(k) for k in keywords)
    return ""


def format_lessons_for_prompt(lessons: list) -> str:
    """Render a list of lesson dicts as a ``### Relevant Lessons from Past Runs`` section.

    Each lesson becomes a numbered block with its rule text, category, and
    keywords. Returns an empty string when ``lessons`` is empty so no section
    header is injected into the prompt.
    """
    if not lessons:
        return ""

    blocks = ["### Relevant Lessons from Past Runs"]
    blocks.append(
        "The following lessons were learned from past runs. Apply them where "
        "relevant to avoid repeating known mistakes."
    )
    blocks.append("")

    for idx, lesson in enumerate(lessons, start=1):
        rule = lesson.get("rule") or lesson.get("proposed_rule") or ""
        category = lesson.get("category", "unknown")
        keywords = _format_keywords(lesson.get("keywords", []))
        blocks.append(f"{idx}. **Rule**: {rule}")
        blocks.append(f"   - Category: {category}")
        if keywords:
            blocks.append(f"   - Keywords: {keywords}")
        blocks.append("")

    return "\n".join(blocks).rstrip() + "\n"
