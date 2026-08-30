"""Markdown writer for the Git-canonical episodic lesson store.

Phase 3.01: appends a promoted lesson to ``ollama_update/lessons.md`` in the
canonical YAML-frontmatter format defined in ``ai_memory_summary.md`` §Canonical
File Formats (Pattern 1). Pure file I/O — no database access, no Ollama calls.
"""

from __future__ import annotations

import os
from typing import Any, Optional


def _format_keywords(keywords: Any) -> str:
    """Render a keywords value (list or string) as a YAML inline list."""
    if isinstance(keywords, str):
        # Accept a JSON-ish string like '["a", "b"]' or a plain string.
        stripped = keywords.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            inner = stripped[1:-1]
            items = [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]
            return "[" + ", ".join(items) + "]"
        return f"[{stripped}]"
    if isinstance(keywords, (list, tuple)):
        return "[" + ", ".join(str(k) for k in keywords) + "]"
    return "[]"


def _format_lesson_block(lesson: dict) -> str:
    """Render a single lesson dict as a YAML-frontmatter markdown block.

    Accepts either the active-lesson shape (``rule`` / ``source_task``) or the
    pending-lesson shape (``proposed_rule`` / ``task_file``) so callers can pass
    a promoted lesson directly.
    """
    rule = lesson.get("rule") or lesson.get("proposed_rule") or ""
    source_task = lesson.get("source_task") or lesson.get("task_file") or ""
    lesson_id = lesson.get("id", "")
    category = lesson.get("category", "unknown")
    keywords = _format_keywords(lesson.get("keywords", []))
    created = lesson.get("created", "")

    lines = [
        "---",
        f"id: {lesson_id}",
        f"category: {category}",
        f"keywords: {keywords}",
        f"created: {created}",
        f"source_task: {source_task}",
        "---",
        f"**Rule**: {rule}",
    ]
    return "\n".join(lines)


def append_lesson_to_markdown(lesson: dict, lessons_md_path: str) -> None:
    """Append a promoted lesson to ``lessons.md`` in canonical YAML-frontmatter form.

    Appends to the end of the file without overwriting existing lessons. Handles
    the first-lesson case (file contains only the skeleton header) naturally,
    since append mode preserves prior content. Creates the file if it does not
    exist.
    """
    block = _format_lesson_block(lesson)

    parent = os.path.dirname(lessons_md_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # Read existing content to decide on separator spacing.
    existing = ""
    if os.path.exists(lessons_md_path):
        with open(lessons_md_path, "r", encoding="utf-8") as f:
            existing = f.read()

    # Ensure a blank line separates the new block from any prior content.
    separator = "\n" if existing and not existing.endswith("\n\n") else ""
    with open(lessons_md_path, "a", encoding="utf-8") as f:
        f.write(f"{separator}{block}\n")
