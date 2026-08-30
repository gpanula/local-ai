# Phase 6 Completion Report — Audit, Promotion & System Rules

> **Status**: ✅ Complete
> **Completed**: 2026-08-30
> **Source plan**: [`memory_multi-phase_implementation_summary.md`](./memory_multi-phase_implementation_summary.md)
> **Approach**: Smallest-first, each sub-section independently testable (6.01–6.05).

---

## Summary

Phase 6 closes the memory lifecycle: the `audit-lessons` CLI clusters related
lessons, promotes recurring patterns into the universal `SYSTEM_RULES.md` store,
and flags low-utility lessons for cleanup. It also makes `pipeline.py`
automatically load `SYSTEM_RULES.md` into both the Author and Reviewer prompts so
promoted invariants are enforced on every run. It builds on the telemetry
counters (`retrieval_count`, `prevented_rework_count`) introduced in Phase 5.

---

## Deliverables by Sub-Section

### 6.01 — Lesson Clustering Engine ✅
Created [`sysadmin/mcp_core/audit.py`](../sysadmin/mcp_core/audit.py):
- `cluster_lessons(lessons, min_cluster_size=3) -> list[dict]` — groups related lessons via union-find over the "related" relation (share ≥2 keywords **or** same category); returns clusters with `count >= min_cluster_size`, sorted by size descending
- Each cluster: `{"keywords": [...], "category": str, "lesson_ids": [...], "count": int}` — keywords are the union of member keywords (lowercased), category is the most common among members
- Pure function — no database or file I/O

### 6.02 — `SYSTEM_RULES.md` Writer ✅
Created [`sysadmin/mcp_core/rules_writer.py`](../sysadmin/mcp_core/rules_writer.py):
- `append_system_rule(rule_text, source_lesson_ids, rules_md_path) -> None` — appends a numbered rule block with provenance
- Auto-increments `### Rule #N` based on existing headers in the file
- Format: `### Rule #N: <Title>` / `**Promoted**: <date> | **Source Lessons**: <ids>` / rule text
- Title derived from the first line of the rule text (truncated to ~60 chars)

### 6.03 — Low-Utility Lesson Flagging ✅
Added to [`sysadmin/mcp_core/audit.py`](../sysadmin/mcp_core/audit.py):
- `flag_low_utility(lessons, min_retrievals=5, max_prevention_ratio=0.3) -> list[dict]` — flags lessons where `retrieval_count >= min_retrievals` AND `prevented_rework_count / retrieval_count < max_prevention_ratio`
- Each flagged lesson gains computed `prevention_ratio` and `utility_score` (reuses the Phase 5 multiplier `(prevented+1)/(retrieved+2)`)
- Pure function — no database or file I/O

### 6.04 — Interactive Audit CLI (`audit-lessons`) ✅
Modified [`sysadmin/mcp_cli/commands/memory.py`](../sysadmin/mcp_cli/commands/memory.py):
- New `AuditLessonsCommand` (`@command`, name `audit-lessons`) registered in the CLI
- Loads all active lessons, runs `cluster_lessons()` + `flag_low_utility()`
- Per cluster: `[p] Promote`, `[m] Modify rule`, `[k] Keep as episodic`, `[d] Discard cluster`
  - **Promote**: `append_system_rule()` → archive source lessons to `ollama_update/lessons_archive.md` → `delete_lesson()` each member
  - **Modify**: prompts for new rule text, then promotes
  - **Keep**: no-op (lessons stay active)
  - **Discard**: `delete_lesson()` each member (no archive)
- Per low-utility lesson: `[d] Delete`, `[m] Rewrite keywords/rule`, `[s] Skip`
- Prints summary at end (Promoted / Modified / Kept / Discarded / Deleted / Rewritten / Skipped)
- Empty store prints `✅ No active lessons to audit.` and exits cleanly

### 6.05 — Pipeline Auto-Load of System Rules ✅
Modified [`sysadmin/mcp_cli/commands/pipeline.py`](../sysadmin/mcp_cli/commands/pipeline.py):
- New `_load_system_rules(rules_path=None) -> str` — reads `sysadmin/prompts/SYSTEM_RULES.md` and wraps it as a `### Universal System Rules` section; returns `""` when the file is missing or empty (no-op, no regression)
- `revision_loop()` prepends the rules section to the Author prompt before lesson injection
- `_build_review_prompt()` / `_review()` accept an optional `rules_section` appended as an additional verification reference
- Rules load failures are logged but never block the pipeline

### Bug Fix — `MemoryStore.update_lesson()` FTS re-sync ✅
Modified [`sysadmin/mcp_core/memory.py`](../sysadmin/mcp_core/memory.py):
- Fixed a pre-existing `sqlite3.DatabaseError: database disk image is malformed` (SQLITE_CORRUPT) that occurred when rewriting a single-keyword lesson (e.g. `["heredoc"]` → `["heredoc","EOF"]`)
- Root cause: `lessons_fts` is an external-content FTS5 table (`content='lessons'`); its `DELETE` reads the current content row, so deleting **after** the content `UPDATE` read the new values and corrupted the index
- Fix: delete from `lessons_fts` **before** updating the content table, then re-insert the new tokens
- This bug was surfaced by the Phase 6 low-utility "rewrite" action, which calls `update_lesson()` with both `rule` and `keywords`

---

## Acceptance Criteria Verification

| Sub-section | Criteria | Result |
|:---|:---|:---|
| 6.01 | 5 lessons about "heredoc" / "EOF" / "delimiter" cluster together | ✅ |
| 6.01 | 2 unrelated lessons do not form a cluster at `min_cluster_size=3` | ✅ |
| 6.01 | Pure function, no database or file I/O | ✅ |
| 6.02 | Appending to skeleton `SYSTEM_RULES.md` produces `### Rule #1` | ✅ |
| 6.02 | Appending a second rule produces `### Rule #2` | ✅ |
| 6.02 | Provenance includes date and source lesson IDs | ✅ |
| 6.03 | Lesson with 8 retrievals / 0 preventions is flagged | ✅ |
| 6.03 | Lesson with 8 retrievals / 4 preventions (50%) is not flagged | ✅ |
| 6.03 | Lesson with 3 retrievals / 0 preventions is not flagged (below threshold) | ✅ |
| 6.04 | `audit-lessons` runs and displays clusters | ✅ |
| 6.04 | Promoted rule appears in `SYSTEM_RULES.md` with correct numbering + provenance | ✅ |
| 6.04 | Archived lessons move to `lessons_archive.md` and are removed from active table | ✅ |
| 6.04 | Low-utility lessons are flagged with stats (retrieval count, prevention ratio) | ✅ |
| 6.05 | With a rule in `SYSTEM_RULES.md`, both Author and Reviewer prompts contain it | ✅ |
| 6.05 | With empty `SYSTEM_RULES.md`, pipeline behavior is unchanged | ✅ |
| 6.05 | Unit tests verify rules are included in both prompts | ✅ |

---

## Verification Commands

```bash
# Phase 6 unit tests (28 new tests across 4 files)
cd sysadmin && ./venv/bin/pytest tests/test_audit.py tests/test_rules_writer.py \
  tests/test_audit_lessons.py tests/test_pipeline.py tests/test_cli.py -v

# Full regression suite (142 passed, 1 skipped)
cd sysadmin && ./venv/bin/pytest tests/ -q

# CLI registration + empty-store run
cd sysadmin && ./venv/bin/python mcp_client.py --help | grep audit-lessons
cd sysadmin && ./venv/bin/python mcp_client.py audit-lessons
```

---

## Notes & Follow-ups

- **Clustering relation**: two lessons are "related" when they share ≥2 keywords **or** have the same category. This is intentionally permissive so same-category lessons can form promotion candidates even without heavy keyword overlap.
- **Keyword normalization**: `cluster_lessons` lowercases keywords (e.g. `EOF` → `eof`) for consistent matching.
- **`lessons_archive.md`**: created on first promotion (did not exist before Phase 6). It reuses the canonical YAML-frontmatter format from `lessons_writer.py`.
- **`update_lesson` fix is a general correctness fix**: it affects any caller rewriting a lesson's searchable fields, not just the Phase 6 rewrite action. Existing Phase 1/3/5 tests continue to pass.
- Phase 6 depends on Phase 5 (telemetry counters for clustering/flagging) and Phase 1 (schema).
- Phase 7 (Trajectories & Wiki) can now build on the promotion/archive flow and the `SYSTEM_RULES.md` store.
