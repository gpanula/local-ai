"""Lesson extraction from reviewer critique + pipeline context.

Phase 2 write-path helpers that convert raw reviewer critique into a structured
lesson dict. ``extract_lesson_from_critique`` uses a constrained LLM extraction
call (``solved_pattern`` / ``hard_failure`` types); ``extract_lesson_from_stuck_loop``
builds a lesson directly from the pipeline's repeating reviewer signature with
zero Ollama invocations (``intractable_pattern`` type).
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Optional

from mcp_core import transport

# Constrained system prompt demanding JSON-only output (no preamble).
_EXTRACTION_SYSTEM_PROMPT = (
    "You are a lesson-extraction engine. Convert the given reviewer critique and "
    "pipeline context into a single structured lesson. "
    "Respond with ONLY a valid JSON object and nothing else — no markdown fences, "
    "no preamble, no commentary. The JSON must have exactly these keys: "
    '"category" (string), "keywords" (array of strings), "proposed_rule" (string).'
)

# Stop-words filtered out of fallback keyword extraction.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "that", "this", "is", "are", "was", "were", "be", "been", "it", "as",
    "at", "by", "from", "your", "you", "must", "should", "not", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "fix",
    "fixes", "issue", "issues", "error", "errors", "please", "script",
}


def _extract_keywords(text: str, limit: int = 5) -> list:
    """Derive coarse keywords from free text via simple tokenization."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text.lower())
    seen = []
    for tok in tokens:
        if tok in _STOPWORDS or tok in seen:
            continue
        seen.append(tok)
        if len(seen) >= limit:
            break
    return seen


def _parse_lesson_json(raw: str) -> Optional[dict]:
    """Best-effort parse of a JSON object from an LLM response.

    Tolerates markdown fences and trailing prose by extracting the first
    balanced JSON object found.
    """
    if not raw:
        return None
    # Strip surrounding markdown fences if present.
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Fall back to scanning for the first {...} block.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def extract_lesson_from_critique(
    critique: str,
    task_file: str,
    prompt_content: str,
    model: str,
    lesson_type: str = "solved_pattern",
    outcome: str = "approved",
) -> dict:
    """Convert raw reviewer critique + pipeline context into a structured lesson.

    Calls ``transport.call_mcp("ollama_chat", ...)`` with a constrained system
    prompt demanding JSON-only output. If the model returns unparseable JSON,
    falls back to a best-effort lesson derived from the raw critique text with
    ``category="unknown"``.
    """
    extraction_prompt = (
        f"### Reviewer Critique:\n{critique}\n\n"
        f"### Task File:\n{task_file}\n\n"
        f"### Task Prompt Context:\n{prompt_content[:2000]}\n\n"
        f"Extract a lesson from the critique above. Output ONLY JSON."
    )

    raw = ""
    try:
        raw = transport.call_mcp("ollama_chat", {
            "prompt": extraction_prompt,
            "model": model,
            "system_prompt": _EXTRACTION_SYSTEM_PROMPT,
            "temperature": 0.1,
            "num_ctx": 2048,
        })
    except Exception:
        raw = ""

    parsed = _parse_lesson_json(raw)
    if parsed:
        return {
            "id": f"lesson-{date.today().strftime('%Y%m%d')}-00",
            "category": str(parsed.get("category", "unknown")),
            "keywords": parsed.get("keywords", []) or [],
            "proposed_rule": str(parsed.get("proposed_rule", critique.strip())),
            "reviewer_critique": critique,
            "task_file": task_file,
            "lesson_type": lesson_type,
            "outcome": outcome,
        }

    # Fallback: best-effort lesson from raw critique text.
    return {
        "id": f"lesson-{date.today().strftime('%Y%m%d')}-00",
        "category": "unknown",
        "keywords": _extract_keywords(critique),
        "proposed_rule": critique.strip(),
        "reviewer_critique": critique,
        "task_file": task_file,
        "lesson_type": lesson_type,
        "outcome": outcome,
    }


def extract_lesson_from_stuck_loop(
    reviewer_history: list,
    abort_reason: str,
    task_file: str,
) -> dict:
    """Build an ``intractable_pattern`` lesson from a repeating reviewer signature.

    Uses the pipeline's existing ``reviewer_history`` (list of critique tuples)
    directly — the repeating signature *is* the lesson. Makes **zero** Ollama
    invocations.
    """
    # Collect the repeating critique points from the history.
    repeating_points: list[str] = []
    for sig in reviewer_history:
        if not sig:
            continue
        if isinstance(sig, (list, tuple)):
            repeating_points.extend(str(p) for p in sig)
        else:
            repeating_points.append(str(sig))

    # De-duplicate while preserving order.
    seen = set()
    unique_points = []
    for p in repeating_points:
        if p not in seen:
            seen.add(p)
            unique_points.append(p)

    critique_text = "\n".join(unique_points) if unique_points else (abort_reason or "")
    proposed_rule = (
        f"Intractable pattern: {critique_text}"
        if critique_text
        else "Intractable pattern: reviewer issued identical critique repeatedly."
    )

    return {
        "id": f"lesson-{date.today().strftime('%Y%m%d')}-00",
        "category": "unknown",
        "keywords": _extract_keywords(critique_text or abort_reason),
        "proposed_rule": proposed_rule,
        "reviewer_critique": critique_text,
        "task_file": task_file,
        "lesson_type": "intractable_pattern",
        "outcome": "aborted",
    }


def extract_lesson_from_success(
    strategy: str,
    risks: str,
    task_file: str,
    prompt_content: str,
    model: str,
    lesson_type: str = "pre_emptive_defense",
) -> Optional[dict]:
    """Extract a positive architectural lesson when a model anticipates risks and succeeds on iteration 1.

    Returns a structured lesson dict with category 'pre_emptive_defense' or None if no substantial
    risks or architectural strategies were identified.
    """
    if not risks or len(risks.strip()) < 30:
        return None

    extraction_prompt = (
        f"### Model Strategy:\n{strategy[:1500]}\n\n"
        f"### Anticipated Risks & Edge Cases:\n{risks[:1500]}\n\n"
        f"### Task Context:\n{prompt_content[:1500]}\n\n"
        "Extract a proven defensive architectural pattern from the proactive strategy and risks above. Output ONLY JSON."
    )

    raw = ""
    try:
        raw = transport.call_mcp("ollama_chat", {
            "prompt": extraction_prompt,
            "model": model,
            "system_prompt": _EXTRACTION_SYSTEM_PROMPT,
            "temperature": 0.1,
            "num_ctx": 2048,
        })
    except Exception:
        raw = ""

    parsed = _parse_lesson_json(raw)
    if parsed:
        return {
            "id": f"lesson-{date.today().strftime('%Y%m%d')}-00",
            "category": str(parsed.get("category", "pre_emptive_defense")),
            "keywords": parsed.get("keywords", []) or _extract_keywords(risks),
            "proposed_rule": str(parsed.get("proposed_rule", risks.strip())),
            "reviewer_critique": "",
            "task_file": task_file,
            "lesson_type": lesson_type,
            "outcome": "approved",
        }

    return {
        "id": f"lesson-{date.today().strftime('%Y%m%d')}-00",
        "category": "pre_emptive_defense",
        "keywords": _extract_keywords(risks),
        "proposed_rule": f"Pre-emptive Defense: {risks.strip().splitlines()[0]}",
        "reviewer_critique": "",
        "task_file": task_file,
        "lesson_type": lesson_type,
        "outcome": "approved",
    }

