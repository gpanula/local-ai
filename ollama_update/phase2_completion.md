# Phase 2 Completion Report — Lesson Staging (Pipeline Write Path)

> **Status**: ✅ Complete
> **Completed**: 2026-08-28
> **Source plan**: [`memory_multi-phase_implementation_summary.md`](./memory_multi-phase_implementation_summary.md)
> **Approach**: Smallest-first, each sub-section independently testable with a human checkpoint after each (2.01–2.04).

---

## Summary

Phase 2 implemented the pipeline **write path**: after any pipeline run where rework
occurred (iteration > 1), a structured lesson is staged in the pending queue —
regardless of whether the run ultimately succeeded or failed. It builds on the
Phase 1 `MemoryStore` data layer and adds LLM-assisted lesson extraction plus a
zero-LLM shortcut for stuck-loop aborts.

---

## Deliverables by Sub-Section

### 2.01 — Pending Lesson CRUD on `MemoryStore` ✅
Added to [`sysadmin/mcp_core/memory.py`](../sysadmin/mcp_core/memory.py):
- `stage_pending_lesson(lesson_dict) → str` — inserts into `pending_lessons`, returns generated `pending-YYYYMMDD-NN` ID
- `list_pending_lessons() → list[dict]` — all pending items, ordered by `staged_at`
- `get_pending_lesson(pending_id) → dict | None`
- `delete_pending_lesson(pending_id)` — removes from pending queue only
- `promote_pending_lesson(pending_id, edits=None)` — moves from `pending_lessons` to `lessons` (with optional field overrides), deletes the pending row
- `_next_pending_id()` — deterministic date-based ID with uniqueness guard

### 2.02 — Lesson Extraction Prompt (LLM-Assisted) ✅
Created [`sysadmin/mcp_core/extraction.py`](../sysadmin/mcp_core/extraction.py):
- `extract_lesson_from_critique(critique, task_file, prompt_content, model, lesson_type, outcome) → dict`
- Calls `transport.call_mcp("ollama_chat", ...)` with a constrained system prompt demanding JSON-only output
- `_parse_lesson_json()` tolerates markdown fences and trailing prose
- Fallback: unparseable JSON → best-effort lesson with `category="unknown"` and tokenized keywords

### 2.03 — Intractable Pattern Shortcut ✅
Added to [`extraction.py`](../sysadmin/mcp_core/extraction.py):
- `extract_lesson_from_stuck_loop(reviewer_history, abort_reason, task_file) → dict`
- Extracts keywords from the repeating critique tuple
- Sets `lesson_type="intractable_pattern"`, `outcome="aborted"`
- Constructs `proposed_rule` from the repeating critique points
- **Zero Ollama invocations** (verified via spy)

### 2.04 — Pipeline Hook & Tests ✅
Updated [`sysadmin/mcp_cli/commands/pipeline.py`](../sysadmin/mcp_cli/commands/pipeline.py):
- Extended `revision_loop()` result with `reviewer_history`, `last_critique`, `rework_occurred`, `lesson_type`
- Added `_stage_lesson_if_rework()` helper, called from `run()` after `revision_loop()` returns
- Exit-state mapping:
  - `iterations == 1 AND approved` → no-op
  - `iterations > 1 AND approved` → `solved_pattern` (LLM extraction)
  - `iterations == max AND not approved AND no abort_reason` → `hard_failure` (LLM extraction)
  - `abort_reason` set → `intractable_pattern` (stuck-loop shortcut, no LLM)
- Terminal banner: `💡 1 new lesson staged in pending queue (type: ...)`
- Staging failures logged via `logger.warning`, never block the pipeline

---

## Acceptance Criteria Verification

| Sub-section | Criteria | Result |
|:---|:---|:---|
| 2.01 | Stage → list → get by ID | ✅ |
| 2.01 | Promote moves row to `lessons` + deletes pending | ✅ |
| 2.01 | Promote with `edits` applies override | ✅ |
| 2.01 | Delete removes from pending, `lessons` unaffected | ✅ |
| 2.02 | Mocked valid JSON → complete lesson dict | ✅ |
| 2.02 | Mocked garbage → valid coarse fallback (no crash) | ✅ |
| 2.02 | Prompt demands only JSON, no preamble | ✅ |
| 2.03 | 3 identical critique tuples → valid lesson dict | ✅ |
| 2.03 | Zero `transport.call_mcp` invocations | ✅ |
| 2.03 | `proposed_rule` captures repeating critique substance | ✅ |
| 2.04 | ≥2 iterations + approval → `solved_pattern` staged, banner | ✅ |
| 2.04 | Max retries exhausted → `hard_failure` staged | ✅ |
| 2.04 | Stuck-loop abort → `intractable_pattern` staged, no extra LLM | ✅ |
| 2.04 | Iteration-1 pass → nothing staged, no banner | ✅ |
| 2.04 | Staging error logs warning, pipeline still reports normally | ✅ |
| 2.04 | All four exit states covered with mocked transport | ✅ |

**Full suite**: `71 passed, 1 skipped` — no regressions (up from 61 in Phase 1; +10 new tests).

---

## Design Decisions

1. **Extend `revision_loop()` return** to expose `reviewer_history` and `last_critique` — the pipeline previously returned neither, but Phase 2.04 needs them for extraction. Backward-compatible addition.
2. **Hook lives in `run()`** via a `_stage_lesson_if_rework()` helper, keeping `revision_loop()` pure and independently testable.
3. **`pending-YYYYMMDD-NN` ID scheme** — distinct from active `lesson-YYYYMMDD-NN` IDs, matching the canonical format in `ai_memory_summary.md`.
4. **Best-effort fallback** — unparseable LLM JSON produces a coarse lesson with `category="unknown"` rather than crashing.
5. **Field mapping on promote** — `proposed_rule → rule`, `task_file → source_task` when moving from `pending_lessons` to `lessons`.

---

## Notes & Deviations

- The `intractable_pattern` path makes **zero** Ollama calls, using the pipeline's existing `reviewer_history` repeating signature directly (per the plan's token-saving note).
- Staging is fully non-blocking: any exception during extraction or DB write is caught and logged, never interrupting the pipeline's normal result reporting.

---

## Files Created / Modified

| File | Action |
|:---|:---|
| `sysadmin/mcp_core/memory.py` | Modified — pending-lesson CRUD + promote |
| `sysadmin/mcp_core/extraction.py` | Created — extraction helpers |
| `sysadmin/mcp_cli/commands/pipeline.py` | Modified — staging hook + extended result |
| `sysadmin/tests/test_extraction.py` | Created — 5 extraction tests |
| `sysadmin/tests/test_pipeline.py` | Modified — 5 staging-hook tests |

---

## Next Steps

Phase 2 is the write path. Per the dependency graph, **Phase 3 (Interactive Review
CLI)** can begin now — it consumes the staged pending lessons via the `review-lessons`
command. **Phase 4 (Lesson Injection / Read Path)** can also run in parallel.
