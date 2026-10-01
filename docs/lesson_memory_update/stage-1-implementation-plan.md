# Stage 1 Implementation Plan: Lexical Dedup Lifecycle

> **Parent**: [stages-overview.md](stages-overview.md)
> **Prerequisites**: None (no new dependencies)
> **Estimated Scope**: ~10 steps across 7 source files + 4 test files

---

## Objective

Eliminate duplicate lessons at every lifecycle transition — ingestion, compaction, promotion, and retrieval — using the existing lexical similarity engine. This stage resolves all issues identified in the [fix doc](fix-lesson-duplication-detection.md), [review doc](review-lesson-duplication-detection.md), and [expert analysis](analysis-lesson-duplication-detection.md) that do not require embedding infrastructure.

---

## Step 1: Normalize Internally & Unify Threshold Constant

### What
Make `are_rules_similar()` call `normalize_lesson_rule()` on both inputs internally so callers never need to pre-normalize. Define a single `DEFAULT_SIMILARITY_THRESHOLD` constant and remove the divergent `0.78` override in `deduplicate_lessons()`.

### Why
The current design allows inconsistent normalization across callsites (some pre-normalize, some don't), and the `0.75` vs `0.78` threshold divergence means the ingestion guard and retrieval deduplication have different duplicate boundaries.

### Where
- `sysadmin/mcp_core/injection.py`: Add `DEFAULT_SIMILARITY_THRESHOLD = 0.75` constant. Modify `are_rules_similar()` to normalize both inputs at function entry. Update `deduplicate_lessons()` to reference the constant instead of hardcoded `0.78`.

### Acceptance Criteria
- `are_rules_similar("Always quote variables!", "always quote variables")` returns `True` (raw vs already-normalized input).
- `deduplicate_lessons()` uses `DEFAULT_SIMILARITY_THRESHOLD` — no hardcoded threshold values remain.
- All existing tests in `test_injection.py` pass without modification (normalization is idempotent).

---

## Step 2: Add Rule-Text Similarity Clustering

### What
Create `cluster_lessons_by_similarity()` as a dedicated function that groups lessons into duplicate clusters using connected components over `are_rules_similar()`. This is separate from the existing `cluster_lessons()` which clusters by metadata/taxonomy for wiki generation.

### Why
The existing `cluster_lessons()` in `audit.py` clusters by shared keywords and category — this serves wiki promotion but is wrong for deduplication compaction. Modifying it would break existing wiki generation and `test_audit.py` tests.

### Where
- `sysadmin/mcp_core/audit.py`: Add `cluster_lessons_by_similarity(lessons, min_cluster_size=2, threshold=DEFAULT_SIMILARITY_THRESHOLD)`. Import `are_rules_similar` and `normalize_lesson_rule` from `injection.py`. Import `DEFAULT_SIMILARITY_THRESHOLD` from `injection.py`.
- Preserve `cluster_lessons()` unchanged for `wiki.py` and `audit-lessons` usage.

### Design Notes
- The function should use the same union-find connected-component pattern as `cluster_lessons()`.
- Pairwise comparison uses `are_rules_similar(a["rule"] or a["proposed_rule"], b["rule"] or b["proposed_rule"])` — rule text only, ignoring category/keywords.
- Return structure should match `cluster_lessons()` output format (list of dicts with `keywords`, `category`, `lesson_ids`, `count`) for compatibility with existing compaction UI.

### Acceptance Criteria
- Given the 8 identical ShellCheck pending lessons from the database audit, `cluster_lessons_by_similarity()` returns 1 cluster with `count=8`.
- Given the 3 near-identical audit pending lessons, returns 1 cluster with `count=3`.
- Given two dissimilar lessons that share a category, they are **not** clustered (unlike `cluster_lessons()`).
- Existing `cluster_lessons()` behavior and tests are unaffected.

---

## Step 3: Ingestion Guard in `stage_pending_lesson()`

### What
Before inserting a new pending lesson, check for near-duplicates in both the active `lessons` table and the existing `pending_lessons` table. Handle matches appropriately with distinct semantics.

### Why
Currently `stage_pending_lesson()` performs an unconditional INSERT. When multiple pipeline runs encounter the same failure (e.g., SC2086), each creates a separate pending row, flooding the queue with duplicates.

### Where
- `sysadmin/mcp_core/memory.py`: Modify `stage_pending_lesson()`.

### Design Notes

**Check order**: Active lessons first, then pending lessons.

**Active lesson match**:
- If the incoming `proposed_rule` is similar to an active lesson's `rule`, the pipeline failed despite the lesson being available. This is a retrieval or model failure, not a new lesson.
- Increment `ineffective_count` on the matching active lesson (via `update_telemetry()`).
- Do **not** insert into `pending_lessons`.
- Return the active lesson's `id`.

**Pending lesson match**:
- If the incoming `proposed_rule` is similar to an existing pending lesson's `proposed_rule`, merge the incoming data into the existing row.
- Merge unique keywords into the existing row's keyword list.
- Append reviewer critique if the incoming lesson has one and the existing doesn't (or concatenate).
- Re-evaluate the category via `normalize_category()` on the merged keyword set.
- Update `staged_at` to the current timestamp.
- Return the existing pending lesson's `id`.

**No match**: Insert new row as before.

**Testability parameter**: Add `deduplicate: bool = True` parameter. When `False`, skip the duplicate checks entirely — this allows test fixtures and migration scripts to populate synthetic duplicate queues.

**Concurrency guard**: Wrap the entire check-then-insert logic in an explicit SQLite transaction (`BEGIN IMMEDIATE` via `self.conn` context manager) to prevent TOCTOU race conditions from concurrent pipeline runs.

**Similarity scan scope**: The scan must be **category-agnostic** — compare against all active/pending lessons regardless of category, since cross-category duplicates exist (e.g., `"ShellCheck"` vs `"Defensive Bash Scripting"` with the same rule text).

### Acceptance Criteria
- Staging the same rule text twice (with `deduplicate=True`) returns the same pending ID and results in only 1 row in `pending_lessons`.
- Staging a rule that already exists in active `lessons` increments `ineffective_count` on the active lesson and does **not** create a pending row.
- Staging with `deduplicate=False` always creates a new row (test support).
- Keywords from the second staging attempt are merged into the first pending row.
- Category is re-evaluated after keyword merge.
- Two concurrent calls to `stage_pending_lesson()` with the same rule do not create two rows (verify via threading test or deterministic serialization check).

---

## Step 4: Promotion Guard in `promote_pending_lesson()`

### What
Before inserting a promoted lesson into the active `lessons` table, check if a near-duplicate active lesson already exists. Return a structured result indicating whether a new lesson was created or an existing one was reinforced.

### Why
Currently `promote_pending_lesson()` blindly inserts into `lessons`. If a lesson was approved multiple times across review sessions, or if a similar lesson was already manually created, the active table accumulates duplicates.

### Where
- `sysadmin/mcp_core/memory.py`: Modify `promote_pending_lesson()` return type and logic.

### Design Notes

**Return contract change**: `promote_pending_lesson()` currently returns `Optional[str]` (the new lesson ID). Change to return `tuple[Optional[str], bool]` where the boolean is `is_new`:
- `(lesson_id, True)` — new active lesson created.
- `(lesson_id, False)` — existing active lesson reinforced.
- `(None, False)` — pending lesson not found.

**Active duplicate match**:
- If `are_rules_similar(pending_rule, active_rule)` finds a match:
  - Merge unique keywords from the pending lesson into the active lesson.
  - Re-evaluate category on the merged keywords.
  - Increment `retrieval_count` or a dedicated reinforcement counter on the active lesson.
  - Delete the pending row.
  - Return `(active_lesson_id, False)`.

**No match**: Insert as before, delete pending, return `(new_lesson_id, True)`.

### Acceptance Criteria
- Promoting a pending lesson that duplicates an active lesson returns `(active_id, False)`.
- Promoting a unique pending lesson returns `(new_id, True)`.
- Keywords from the promoted duplicate are merged into the active lesson.
- The pending row is always deleted regardless of match outcome.
- Return type is `tuple[Optional[str], bool]` in all code paths.

---

## Step 5: Fix Caller Desync in CLI and TUI

### What
Update all callers of `promote_pending_lesson()` to handle the new `(lesson_id, is_new)` return contract and prevent `lessons.md` desync.

### Why
The current callers (`ReviewLessonsCommand` in CLI, `ReviewLessonsApp` in TUI) pass the promoted lesson to `append_lesson_to_markdown()` unconditionally. When the promotion guard returns an existing active ID (reinforcement), this would create duplicate entries in `lessons.md`.

### Where
- `sysadmin/mcp_cli/commands/memory.py`: Update `ReviewLessonsCommand` promotion flow.
- `sysadmin/lessons_tui/app.py`: Update `ReviewLessonsApp` promotion flow.

### Design Notes

When `is_new=True`: Call `append_lesson_to_markdown()` as before.
When `is_new=False`: If keywords or rule were enriched during the merge, call `write_all_lessons_to_markdown()` to re-sync the full file. If nothing changed, skip the markdown write entirely.

### Acceptance Criteria
- Promoting a duplicate pending lesson via CLI does not create a duplicate entry in `lessons.md`.
- Promoting a duplicate pending lesson via TUI does not create a duplicate entry in `lessons.md`.
- Promoting a unique pending lesson via either path correctly appends to `lessons.md`.
- After a reinforcement promotion that enriches keywords, `lessons.md` reflects the updated keywords.

---

## Step 6: Wire Similarity Clustering into Compaction

### What
Update the compaction flows (`_compact_pending()`, `_compact_active()`, `CompactQueueApp`) to use `cluster_lessons_by_similarity()` instead of (or alongside) the existing metadata-based `cluster_lessons()`.

### Why
The existing compaction only groups by shared keywords and category, missing text-similar duplicates with slight keyword differences.

### Where
- `sysadmin/mcp_cli/commands/memory.py`: Update `_compact_pending()` and `_compact_active()`.
- `sysadmin/lessons_tui/compact_app.py`: Update `CompactQueueApp`.

### Design Notes

**Compaction merge strategy**:
- Select the longest/richest rule text as the primary rule (`max(rules, key=len)`).
- Union all keywords and deduplicate.
- Re-evaluate category via `normalize_category()` on the merged keyword set.
- Aggregate telemetry counters (sum `retrieval_count`, `prevented_rework_count`, `ineffective_count` across merged members).
- Delete all non-primary members.

**Stale embedding invalidation**: When `_compact_active()` updates an active lesson's rule text, set `embeddings = NULL` on that row. This prevents `sqlite-vec` from returning stale semantic matches. (Embeddings will be regenerated in Stage 2A.)

**Markdown re-sync**: After compaction, call `write_all_lessons_to_markdown()` to rebuild `lessons.md` from the clean state.

### Acceptance Criteria
- `localai-compact --dry-run` shows the 8 ShellCheck items grouped as 1 cluster and the 3 audit items as 1 cluster.
- `localai-compact --auto` reduces the pending queue from 17 to ≤6 unique items.
- Active lesson compaction reduces duplicates (expected: 66 → ~28 distinct).
- Stale embeddings are NULLed after rule text changes.
- `lessons.md` is cleanly regenerated after compaction.

---

## Step 7: Lesson Decay / Sunset Flagging

### What
Extend `flag_low_utility()` to identify lessons that should be considered for retirement.

### Why
Without decay detection, the active lesson table accumulates zombie lessons about deprecated patterns that consume retrieval bandwidth and FTS index space.

### Where
- `sysadmin/mcp_core/audit.py`: Extend `flag_low_utility()` with new flagging criteria.
- `sysadmin/mcp_cli/commands/memory.py`: Surface sunset candidates in `localai-compact --dry-run` output.

### Design Notes

Additional flagging criteria beyond the existing ratio-based check:
- **Never-retrieved**: `retrieval_count == 0` and `created` is older than a configurable threshold (e.g., 30 days). A lesson that's never been retrieved in a month is likely not relevant to current work.
- **Consistently ineffective**: `ineffective_count > 0` and `ineffective_count / (retrieval_count + ineffective_count) > 0.5`. The lesson is being retrieved but consistently failing to prevent the problem it describes.

Flag type should be included in the output so operators can distinguish between "never useful" and "actively harmful" lessons.

### Acceptance Criteria
- A lesson with `retrieval_count=0` and `created` 45 days ago is flagged as a sunset candidate.
- A lesson with `retrieval_count=10`, `prevented_rework_count=1`, `ineffective_count=8` is flagged.
- A lesson with `retrieval_count=10`, `prevented_rework_count=7`, `ineffective_count=1` is **not** flagged.
- `localai-compact --dry-run` displays sunset candidates with their flag reason.

---

## Step 8: Update Test Fixtures

### What
Update existing test fixtures that rely on metadata-only clustering or unrestricted staging, and add new test cases for all modified behaviors.

### Why
Tests in `test_compact_lessons.py` and `test_compact_queue_tui.py` staged dissimilar rules that clustered only because they shared a category. Under rule-similarity clustering, these tests will fail. Additionally, tests staging multiple items need to use `deduplicate=False` or use authentic phrasing variants.

### Where
- `sysadmin/tests/test_compact_lessons.py`: Update fixtures to use phrasing variants; adjust for `cluster_lessons_by_similarity()`.
- `sysadmin/tests/test_compact_queue_tui.py`: Same.
- `sysadmin/tests/test_memory.py`: Add tests for `stage_pending_lesson()` dedup, `promote_pending_lesson()` guard, and telemetry semantics.
- `sysadmin/tests/test_audit.py`: Add tests for `cluster_lessons_by_similarity()`. Ensure existing `cluster_lessons()` tests pass unchanged.
- `sysadmin/tests/test_injection.py`: Add tests for internal normalization in `are_rules_similar()` and unified threshold.

### Acceptance Criteria
- All pre-existing tests pass (no regressions).
- New tests cover: ingestion dedup (active match, pending match, no match), promotion guard (`is_new=True`, `is_new=False`), similarity clustering, sunset flagging.

---

## Step 9: Full Lifecycle Integration Test

### What
Add an integration test that exercises the complete lesson lifecycle from staging through prompt injection output.

### Why
All bugs discovered in the original investigation were cross-component interaction failures. Unit tests on individual functions don't catch these.

### Where
- `sysadmin/tests/test_lesson_lifecycle.py` (new file).

### Design Notes

The integration test should exercise the following sequence in a single test case:
1. Stage 5 duplicate lessons via `stage_pending_lesson()` with `deduplicate=True`.
2. Assert only 1 pending row exists in the database.
3. Stage another variant with `deduplicate=False` (simulating a test setup).
4. Run compaction and verify cluster detection.
5. Promote the lesson to active memory.
6. Stage another similar lesson — assert it hits the active match path, bumps `ineffective_count`, and does **not** create a pending row.
7. Query via `collect_relevant_lessons()` with tags that should match the lesson.
8. Assert the returned lessons contain no duplicates.
9. Verify `lessons.md` contains exactly 1 entry for the lesson.

### Acceptance Criteria
- The integration test passes end-to-end.
- The test uses a temporary database (`:memory:` or `tmp_path`) to avoid side effects.
- Test is self-contained — no dependency on real database state.

---

## Step 10: Execute One-Time Compaction & Commit

### What
Run `localai-compact --auto` against the production `.localai/memory.db` to clean up existing duplicates, then commit all changes.

### Why
The existing database has 11 redundant duplicates in the pending queue and an estimated 38 duplicate active lessons. The new compaction logic should clean these up.

### Where
- Run against `.localai/memory.db`.
- Commit with bisectable conventional gitmoji commits per AGENTS.md.

### Design Notes

**Execution sequence**:
1. Run `localai-compact --dry-run` first to preview the cleanup.
2. Verify the preview matches expectations (pending: 17 → ≤6, active: 66 → ~28).
3. Run `localai-compact --auto` to execute.
4. Verify `lessons.md` and `ollama_update/wiki` are cleanly regenerated.
5. Run the full test suite to confirm no regressions.

**Commit strategy**:
- Separate commits for: (a) core similarity/threshold changes, (b) ingestion/promotion guards, (c) compaction upgrades, (d) test updates, (e) database cleanup. This ensures bisectability.

### Acceptance Criteria
- `localai-compact --dry-run` shows expected cluster counts.
- `localai-compact --auto` executes without errors.
- Pending lessons: ≤6 unique items.
- Active lessons: ~28 distinct (no near-duplicate rules).
- `lessons.md` is clean and consistent with `memory.db`.
- Full test suite (363+ tests) passes.
- All changes committed with gitmoji conventional commits on an appropriate feature branch.
