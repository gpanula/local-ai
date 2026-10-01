"""Markdown formatter for injecting relevant lessons into the Author prompt.

Phase 4.01: renders a list of lesson dicts as a human-readable markdown section
suitable for prepending to the Author prompt. Pure function — no database access,
no Ollama calls, no raw JSON in the output.
"""

from __future__ import annotations

import difflib
import re
from typing import Any


def normalize_lesson_rule(rule: str) -> str:
    """Normalize rule text for deduplication.

    Collapses whitespace, strips non-alphanumeric punctuation, and lowercases
    to detect duplicate rules even if punctuation or whitespace vary slightly.
    """
    if not rule:
        return ""
    cleaned = re.sub(r"[^\w\s]", "", rule)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def are_rules_similar(rule1: str, rule2: str, threshold: float = 0.75) -> bool:
    """Determine whether two normalized rule texts are near-duplicates.

    Evaluates word-level Jaccard similarity and character-level SequenceMatcher ratio.
    Requires significant token overlap (jaccard >= threshold and ratio >= 0.70)
    or an overwhelmingly high character match on sufficiently long rules (ratio >= 0.92
    and min(len(rule1), len(rule2)) > 25) to avoid false positives on short test
    labels (e.g. 'Rule A' vs 'Rule C' or 'bash lesson 0' vs 'bash lesson 1').
    """
    if not rule1 or not rule2:
        return False
    if rule1 == rule2:
        return True

    ratio = difflib.SequenceMatcher(None, rule1, rule2).ratio()
    if ratio >= 0.92 and min(len(rule1), len(rule2)) > 25:
        return True

    tokens1 = set(rule1.split())
    tokens2 = set(rule2.split())
    if tokens1 and tokens2:
        jaccard = len(tokens1 & tokens2) / len(tokens1 | tokens2)
        if jaccard >= threshold and ratio >= 0.70:
            return True

    return False


def deduplicate_lessons(lessons: list, similarity_threshold: float = 0.78) -> list:
    """Deduplicate a list of lesson dicts by ID and normalized rule text.

    Preserves the original ranking/relevance order so the highest-scoring
    version of a lesson is retained while subsequent exact duplicates or
    near-duplicate variations (evaluated via `are_rules_similar`) are dropped.
    """
    if not lessons:
        return []

    seen_ids = set()
    seen_rules: list[str] = []
    deduped = []

    for lesson in lessons:
        if not isinstance(lesson, dict):
            continue
        lesson_id = lesson.get("id")
        rule = lesson.get("rule") or lesson.get("proposed_rule") or ""
        norm_rule = normalize_lesson_rule(rule)

        if lesson_id and lesson_id in seen_ids:
            continue
        if norm_rule:
            is_dup = False
            for prev_rule in seen_rules:
                if norm_rule == prev_rule or are_rules_similar(norm_rule, prev_rule, threshold=similarity_threshold):
                    is_dup = True
                    break
            if is_dup:
                continue

        if lesson_id:
            seen_ids.add(lesson_id)
        if norm_rule:
            seen_rules.append(norm_rule)

        deduped.append(lesson)

    return deduped


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
    keywords. Duplicate lessons (by ID or normalized rule text) are automatically
    filtered out before rendering. Returns an empty string when ``lessons`` is empty
    so no section header is injected into the prompt.
    """
    lessons = deduplicate_lessons(lessons)
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
