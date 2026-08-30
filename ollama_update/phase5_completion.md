# Phase 5 Completion Report — Retrieval Telemetry & Attribution

> **Status**: ✅ Complete
> **Completed**: 2026-08-29
> **Source plan**: [`memory_multi-phase_implementation_summary.md`](./memory_multi-phase_implementation_summary.md)
> **Approach**: Smallest-first, each sub-section independently testable (5.01–5.03).

---

## Summary

Phase 5 closed the feedback loop on Phase 4's lesson injection: it tracks whether injected
lessons actually prevented rework, and decays ineffective lessons out of top-K results over
time. It builds on the `injected_lessons` tracking introduced in Phase 4.04 and the
`retrieval_count` / `prevented_rework_count` / `ineffective_count` counter columns that have
existed on the `lessons` table since Phase 1.

---

## Deliverables by Sub-Section

### 5.01 — Retrieval Counter Updates ✅
Modified [`sysadmin/mcp_core/memory.py`](../sysadmin/mcp_core/memory.py):
- `MemoryStore.increment_retrieval_count(lesson_ids: list[str]) -> None` — batch-increments `retrieval_count` for each ID; no-op on an empty list; persists to disk
- `MemoryStore.update_telemetry(lesson_id, field, increment=1) -> None` — generic counter update guarded to the three telemetry fields (`retrieval_count`, `prevented_rework_count`, `ineffective_count`); unknown fields are ignored

### 5.02 — Attribution Logic (Blame / Innocent / Credit) ✅
Created [`sysadmin/mcp_core/attribution.py`](../sysadmin/mcp_core/attribution.py):
- `attribute_lessons(injected_lessons, pipeline_result, reviewer_critique) -> dict[str, str]` — returns `lesson_id → "credited" | "blamed" | "innocent"`
- **Pass on iteration 1** (no rework): all injected lessons → `"credited"`
- **Rework occurred**: compares each lesson's keywords against the reviewer-critique keywords (stop-word-filtered tokenization, mirroring `extraction.py`); overlap → `"blamed"`, no overlap → `"innocent"`
- Handles keywords as a list or JSON string; skips lessons without an ID

### 5.03 — Dynamic Ranking Suppression & Tests ✅
Modified [`sysadmin/mcp_core/memory.py`](../sysadmin/mcp_core/memory.py):
- `search_lessons()` now computes a `utility_score = (-bm25_rank + 1) × ((prevented + 1) / (retrieved + 2))` and sorts by it, suppressing frequently-retrieved-but-ineffective lessons below the top-K threshold
- `search_lessons_hybrid()` applies the same utility multiplier to the combined FTS5 + vector score
- A brand-new lesson (0 retrieved, 0 prevented) gets a neutral `0.5` multiplier — not penalized

### Pipeline Hook ✅
Modified [`sysadmin/mcp_cli/commands/pipeline.py`](../sysadmin/mcp_cli/commands/pipeline.py):
- `_inject_lessons()` now returns lesson dicts (not just IDs) so attribution can read `keywords`; `revision_loop()` keeps `injected_lessons` as IDs for backward compatibility and exposes `injected_lesson_dicts`
- New `_apply_telemetry(result)` called from `run()` after `revision_loop()`: increments `retrieval_count` for every injected lesson, then applies attribution (`credited` → `prevented_rework_count += 1`, `blamed` → `ineffective_count += 1`, `innocent` → no change)
- Telemetry failures are logged but never block the pipeline

---

## Acceptance Criteria Verification

| Sub-section | Criteria | Result |
|:---|:---|:---|
| 5.01 | After a run injecting lessons A and B, both have `retrieval_count += 1` | ✅ |
| 5.01 | Running with no injected lessons does not modify any rows | ✅ |
| 5.01 | Counter survives across MemoryStore sessions (persisted to disk) | ✅ |
| 5.02 | Iteration-1 pass credits all injected lessons | ✅ |
| 5.02 | Lesson with keyword "heredoc" is blamed when critique mentions "heredoc" | ✅ |
| 5.02 | Lesson with keyword "ansible" is innocent when critique is about "heredoc" | ✅ |
| 5.02 | Counters reflect the attribution correctly in the database | ✅ |
| 5.03 | Lesson retrieved 10× / 0 prevented ranks lower than 2× / 1 prevented (similar BM25) | ✅ |
| 5.03 | Brand-new lesson (0/0) gets a neutral 0.5 multiplier — not penalized | ✅ |
| 5.03 | Unit tests with synthetic counters verify ranking order changes | ✅ |

---

## Verification Commands

```bash
# Phase 5 unit tests (17 new tests across 3 files)
cd sysadmin && ./venv/bin/pytest tests/test_attribution.py tests/test_memory.py tests/test_pipeline.py -v

# Full regression suite (114 passed, 1 skipped)
cd sysadmin && ./venv/bin/pytest tests/ -q
```

---

## Notes & Follow-ups

- **Suppression formula**: BM25 `rank` is negative (lower = better). The utility score uses `(-rank + 1) × multiplier` so that even when BM25 ranks are identical (e.g. identical rule text), the utility multiplier still breaks the tie — a lesson retrieved 10× with 0 preventions ranks below one retrieved 2× with 1 prevention.
- **`_inject_lessons` return type change**: it now returns lesson dicts (needed for attribution keyword reads). `revision_loop`'s `injected_lessons` field remains a list of IDs, so Phase 4 consumers are unaffected.
- **No schema migration needed**: the three telemetry counter columns have existed since Phase 1.
- Phase 5 depends on Phase 4 (injection / `injected_lessons` tracking) and Phase 1 (counter columns).
- Phase 6 (Audit, Promotion & System Rules) can now build on the telemetry data — clustering and low-utility flagging consume `retrieval_count` / `prevented_rework_count`.
