"""Attribution logic for injected lessons (Phase 5.02).

Determines whether each lesson injected into the Author prompt helped, was
irrelevant, or was actively harmful, based on the pipeline outcome and the
reviewer critique. Pure function — no database access, no Ollama calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Stop-words filtered out of critique keyword extraction (mirrors extraction.py).
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "that", "this", "is", "are", "was", "were", "be", "been", "it", "as",
    "at", "by", "from", "your", "you", "must", "should", "not", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "fix",
    "fixes", "issue", "issues", "error", "errors", "please", "script",
}


def _extract_keywords(text: str, limit: int = 10) -> set:
    """Derive a set of significant keyword tokens from free text."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", (text or "").lower())
    return {tok for tok in tokens if tok not in _STOPWORDS}


def _lesson_keywords(lesson: dict) -> set:
    """Return the normalized keyword set for a lesson dict."""
    keywords = lesson.get("keywords", [])
    if isinstance(keywords, str):
        try:
            import json

            parsed = json.loads(keywords)
            if isinstance(parsed, list):
                keywords = parsed
        except (json.JSONDecodeError, TypeError):
            keywords = []
    if not isinstance(keywords, (list, tuple)):
        keywords = []
    return {str(k).lower() for k in keywords}


def attribute_lessons(
    injected_lessons: List[dict],
    pipeline_result: dict,
    reviewer_critique: str,
) -> Dict[str, str]:
    """Attribute each injected lesson to ``credited``, ``blamed``, or ``innocent``.

    Logic:
      - Pass on iteration 1 (no rework): all injected lessons -> ``credited``.
      - Rework occurred (iterations > 1): compare each lesson's keywords against
        the reviewer-critique keywords:
          - Overlap found -> ``blamed``.
          - No overlap -> ``innocent``.

    Returns a mapping of ``lesson_id -> attribution``.
    """
    iterations = int(pipeline_result.get("iterations", 0))
    approved = bool(pipeline_result.get("approved", False))
    no_rework = iterations == 1 and approved

    critique_keywords = _extract_keywords(reviewer_critique)

    attribution: Dict[str, str] = {}
    for lesson in injected_lessons:
        lesson_id = lesson.get("id")
        if lesson_id is None:
            continue
        if no_rework:
            attribution[lesson_id] = "credited"
        else:
            overlap = _lesson_keywords(lesson) & critique_keywords
            attribution[lesson_id] = "blamed" if overlap else "innocent"
    return attribution
