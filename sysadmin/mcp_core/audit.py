"""Audit utilities for lesson clustering and low-utility flagging (Phase 6).

Phase 6.01/6.03: pure functions that operate on lists of lesson dicts — no
database or file I/O. ``cluster_lessons`` groups related lessons to identify
promotion candidates; ``flag_low_utility`` surfaces lessons that are retrieved
frequently but never prevent rework.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List


def _normalize_keywords(lesson: dict) -> set:
    """Return the normalized (lowercased) keyword set for a lesson dict."""
    keywords = lesson.get("keywords", [])
    if isinstance(keywords, str):
        try:
            parsed = json.loads(keywords)
            if isinstance(parsed, list):
                keywords = parsed
        except (json.JSONDecodeError, TypeError):
            keywords = []
    if not isinstance(keywords, (list, tuple)):
        keywords = []
    return {str(k).strip().lower() for k in keywords if str(k).strip()}


def _related(a: dict, b: dict) -> bool:
    """Return True if two lessons are related (share >=2 keywords or same category)."""
    shared = _normalize_keywords(a) & _normalize_keywords(b)
    if len(shared) >= 2:
        return True
    cat_a = (a.get("category") or "").strip().lower()
    cat_b = (b.get("category") or "").strip().lower()
    return bool(cat_a and cat_a == cat_b)


def cluster_lessons(lessons: List[dict], min_cluster_size: int = 3) -> List[dict]:
    """Group related lessons into clusters of promotion candidates.

    Two lessons are related when they share >=2 keywords or have the same
    category. Clusters are formed via connected components over that relation.
    Only clusters with ``count >= min_cluster_size`` are returned, sorted by
    cluster size descending.

    Each cluster is a dict::

        {
            "keywords": [...],   # union of member keywords (deduped)
            "category": str,     # most common category among members
            "lesson_ids": [...], # member lesson IDs
            "count": int,        # number of members
        }

    Pure function — no database or file I/O.
    """
    lessons = list(lessons)
    n = len(lessons)
    if n == 0:
        return []

    # Union-find over the "related" relation.
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(n):
        for j in range(i + 1, n):
            if _related(lessons[i], lessons[j]):
                union(i, j)

    # Group members by root.
    groups: Dict[int, List[int]] = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(idx)

    clusters = []
    for members in groups.values():
        if len(members) < min_cluster_size:
            continue
        member_lessons = [lessons[i] for i in members]
        keyword_counter: Counter = Counter()
        category_counter: Counter = Counter()
        for lesson in member_lessons:
            keyword_counter.update(_normalize_keywords(lesson))
            cat = (lesson.get("category") or "unknown").strip()
            if cat:
                category_counter[cat] += 1
        clusters.append(
            {
                "keywords": sorted(keyword_counter),
                "category": category_counter.most_common(1)[0][0] if category_counter else "unknown",
                "lesson_ids": [lesson.get("id") for lesson in member_lessons],
                "count": len(members),
            }
        )

    clusters.sort(key=lambda c: c["count"], reverse=True)
    return clusters


def _utility_score(lesson: dict) -> float:
    """Reuse the Phase 5 utility multiplier ``(prevented+1)/(retrieved+2)``."""
    retrieved = int(lesson.get("retrieval_count", 0))
    prevented = int(lesson.get("prevented_rework_count", 0))
    return (prevented + 1) / (retrieved + 2)


def flag_low_utility(
    lessons: List[dict],
    min_retrievals: int = 5,
    max_prevention_ratio: float = 0.3,
) -> List[dict]:
    """Flag lessons retrieved frequently but rarely preventing rework.

    A lesson is flagged when ``retrieval_count >= min_retrievals`` AND
    ``prevented_rework_count / retrieval_count < max_prevention_ratio``. Each
    flagged lesson is returned with computed ``prevention_ratio`` and
    ``utility_score`` fields added.

    Pure function — no database or file I/O.
    """
    flagged = []
    for lesson in lessons:
        retrieved = int(lesson.get("retrieval_count", 0))
        prevented = int(lesson.get("prevented_rework_count", 0))
        if retrieved < min_retrievals:
            continue
        prevention_ratio = prevented / retrieved if retrieved else 0.0
        if prevention_ratio >= max_prevention_ratio:
            continue
        flagged_lesson = dict(lesson)
        flagged_lesson["prevention_ratio"] = prevention_ratio
        flagged_lesson["utility_score"] = _utility_score(lesson)
        flagged.append(flagged_lesson)
    return flagged
