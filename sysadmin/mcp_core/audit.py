"""Audit utilities for lesson clustering and low-utility flagging (Phase 6).

Phase 6.01/6.03: pure functions that operate on lists of lesson dicts — no
database or file I/O. ``cluster_lessons`` groups related lessons to identify
promotion candidates; ``flag_low_utility`` surfaces lessons that are retrieved
frequently but never prevent rework.

Category taxonomy (Phase 6.10): ``normalize_category`` maps LLM-generated
free-form category strings to a controlled vocabulary at ingestion time. This
prevents vocabulary fragmentation (e.g. "Script Robustness" vs "Scripting
Best Practices") from breaking keyword-based clustering. The taxonomy is
keyword-driven: the category with the most matching signal keywords wins, with
the raw LLM category used as a tiebreaker signal and "unknown" as the fallback.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from mcp_core.workspace import WORKSPACE_ROOT

DEFAULT_TAXONOMY_PATH = os.path.join(WORKSPACE_ROOT, "ollama_update", "taxonomy.json")

# ---------------------------------------------------------------------------
# Category taxonomy (Phase 6.10)
# ---------------------------------------------------------------------------

# Built-in fallback taxonomy if taxonomy.json is not present or unreadable.
CATEGORY_TAXONOMY: Dict[str, List[str]] = {
    "Defensive Bash Scripting": [
        "bash", "scripting", "trap", "exit", "exit codes", "err", "error handling",
        "cleanup", "set -euo", "pipefail", "defensive", "success message", "guard",
        "standalone", "script structure", "required output", "resources management",
        "bash scripting", "diagnostic trap", "conditional success",
    ],
    "Binary Isolation": [
        "binary", "venv", "virtual environment", "binary isolation", "binary assertions",
        "binary existence", "pre-execution", "executable", "path", "isolation",
        "bin directory", "deterministic resolution", "venv_dir", "repo_root",
        "hardcoded paths", "dynamic resolution", "environment variables",
    ],
    "ShellCheck": [
        "shellcheck", "sc2034", "sc2016", "sc2086", "sc2046", "sc1003", "sc1009",
        "sc1050", "sc1064", "sc1065", "sc1072", "sc1073", "sc1078", "sc1079",
        "linter", "linters", "pre-flight", "quoting", "variable naming",
        "word splitting", "shellcheck findings", "intractable pattern",
    ],
    "Ansible": [
        "ansible", "yaml", "playbook", "become", "privilege", "task", "role",
        "inventory", "ansible sandbox", "yaml parsing",
    ],
    "Python Quality": [
        "python", "syntax", "validation", "parsing", "pytest", "unit test",
        "python syntax", "python validation",
    ],
    "Code Quality Toolchain": [
        "code quality", "pre-flight linters", "toolchain", "functional test suites",
        "linter toolchain", "verification script",
    ],
    "Security & Hardening": [
        "security", "stride", "privilege", "seccomp", "socket isolation",
        "bubblewrap", "sandbox", "permissions", "vulnerability", "exploit",
        "path traversal", "hardening", "attack surface",
    ],
    "Multi-Agent Orchestration": [
        "orchestration", "orchestrator", "workflow", "decomposition",
        "acceptance gates", "multi-agent", "pipeline", "revision loop", "role dispatch",
    ],
    "System Architecture": [
        "architecture", "topology", "modular design", "component boundaries",
        "scalability", "interface contract", "data model", "system design",
    ],
}

# Aliases: raw LLM category strings (lowercased) → canonical name.
_CATEGORY_ALIASES: Dict[str, str] = {
    "scripting best practices": "Defensive Bash Scripting",
    "scripting practices": "Defensive Bash Scripting",
    "script robustness": "Defensive Bash Scripting",
    "script output compliance": "Defensive Bash Scripting",
    "script creation method": "Defensive Bash Scripting",
    "script structure": "Defensive Bash Scripting",
    "script development": "Binary Isolation",
    "script modification": "Binary Isolation",
    "code quality & pre-flight linters": "ShellCheck",
    "shellcheck": "ShellCheck",
    "ansible": "Ansible",
    "python quality": "Python Quality",
    "code quality toolchain": "Code Quality Toolchain",
    "threat modeling": "Security & Hardening",
    "privilege escalation": "Security & Hardening",
    "sandboxing": "Security & Hardening",
    "security hardening": "Security & Hardening",
    "workflow coordination": "Multi-Agent Orchestration",
    "task planning": "Multi-Agent Orchestration",
    "pipeline orchestration": "Multi-Agent Orchestration",
    "system design": "System Architecture",
    "architectural specification": "System Architecture",
}


def load_taxonomy(taxonomy_path: Optional[str] = None) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Load taxonomy and alias mappings from a JSON file, falling back to built-ins."""
    path = taxonomy_path or DEFAULT_TAXONOMY_PATH
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            taxonomies = data.get("taxonomies", {})
            aliases = data.get("aliases", {})
            if isinstance(taxonomies, dict) and isinstance(aliases, dict):
                # Lowercase alias keys for fast case-insensitive lookup
                normalized_aliases = {k.lower(): str(v) for k, v in aliases.items()}
                return taxonomies, normalized_aliases
        except Exception:
            pass
    return CATEGORY_TAXONOMY, _CATEGORY_ALIASES


def is_canonical_category(category: str, taxonomy_path: Optional[str] = None) -> bool:
    """Check if a given category is a recognized canonical domain."""
    if not category or category.strip().lower() == "unknown":
        return False
    taxonomies, _ = load_taxonomy(taxonomy_path)
    cat_lower = category.strip().lower()
    return any(c.lower() == cat_lower for c in taxonomies.keys())


def add_taxonomy_domain(
    domain: str,
    keywords: List[str],
    aliases: Optional[List[str]] = None,
    taxonomy_path: Optional[str] = None,
) -> None:
    """Register a new domain and optional aliases into taxonomy.json."""
    path = taxonomy_path or DEFAULT_TAXONOMY_PATH
    taxonomies, alias_map = load_taxonomy(path)
    # Copy to mutable dicts
    taxonomies = dict(taxonomies)
    alias_map = dict(alias_map)

    taxonomies[domain] = sorted(list(set(keywords)))
    if aliases:
        for a in aliases:
            alias_map[a.lower()] = domain

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"taxonomies": taxonomies, "aliases": alias_map}, f, indent=2)


def normalize_category(keywords: list, raw_category: str = "", taxonomy_path: Optional[str] = None) -> str:
    """Map a free-form LLM category string to the closest canonical taxonomy entry.

    Algorithm:
    1. Dynamic load: loads taxonomy definitions and aliases from taxonomy.json.
    2. Alias lookup: if ``raw_category`` (lowercased) is in aliases, return mapped canonical name.
    3. Keyword scoring: count signal-keyword matches between (keywords ∪ raw_category tokens)
       and each taxonomy entry's keyword list. Pick highest scoring category.
    4. Fallback: return ``raw_category`` unchanged if non-empty, otherwise return ``"unknown"``.
    """
    taxonomies, alias_map = load_taxonomy(taxonomy_path)
    raw_lower = (raw_category or "").strip().lower()

    # Step 1: alias fast-path.
    if raw_lower in alias_map:
        return alias_map[raw_lower]

    # Build a combined signal set from the lesson's keywords + raw category tokens.
    kw_set = {str(k).strip().lower() for k in (keywords or []) if str(k).strip()}
    kw_set.update(raw_lower.split())

    # Step 2: score each taxonomy entry.
    best_category: Optional[str] = None
    best_score = 0
    for canonical, signals in taxonomies.items():
        score = sum(1 for sig in signals if sig in kw_set)
        if score > best_score:
            best_score = score
            best_category = canonical

    if best_score >= 1 and best_category:
        return best_category

    # Step 3: fallback.
    return raw_category.strip() if raw_category.strip() else "unknown"


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
