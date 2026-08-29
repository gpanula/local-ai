# AI Memory System — Multi-Phase Implementation Outline

> **Source**: [`ai_memory_summary.md`](./ai_memory_summary.md)
> **Created**: 2026-08-25
> **Approach**: Smallest-first, each phase independently testable with clear acceptance gates.

---

## Phase 1 — Scaffolding & Data Layer (~1 day)

> **Status**: ✅ **COMPLETE** — implemented 2026-08-28. See [`phase1_completion.md`](./phase1_completion.md) for the full completion report.

**Goal**: Create the directory structure, SQLite schema, and pure-Python data access layer. No Ollama calls, no embeddings — just deterministic CRUD and FTS5 keyword search.

### Phase 1.01 — Directory Structure & Git Hygiene

**Goal**: Create all directories and skeleton files. Pure file creation, zero code logic.

**Deliverables**:
- `.localai/` directory at repo root (runtime data, never committed)
- `sysadmin/data/` directory (future trajectory storage)
- `.gitignore` updated: add `.localai/` entry
- `sysadmin/prompts/SYSTEM_RULES.md` — skeleton with header and empty rules section
- `ollama_update/lessons.md` — skeleton with header and format instructions

**Acceptance Criteria**:
- [x] `.localai/` directory exists and is excluded by `git check-ignore -v .localai/`
- [x] `sysadmin/data/` directory exists
- [x] `SYSTEM_RULES.md` and `lessons.md` are valid markdown with clear header sections

### Phase 1.02 — SQLite Schema & `MemoryStore` Init

**Goal**: Create `sysadmin/mcp_core/memory.py` with the `MemoryStore` class, schema creation, and database connection lifecycle. No data operations yet — just open, create tables, close.

**Deliverables**:
- `sysadmin/mcp_core/memory.py` with `MemoryStore` class
- `__init__()` → opens/creates `.localai/memory.db`, runs `CREATE TABLE IF NOT EXISTS` for:
  - `lessons` — active approved lessons (id, category, keywords, rule, created, source_task, lesson_type, retrieval_count, prevented_rework_count, ineffective_count)
  - `pending_lessons` — staged awaiting human review (id, staged_at, task_file, proposed_rule, category, keywords, reviewer_critique, lesson_type, outcome)
  - `lessons_fts` — FTS5 virtual table over lessons (rule, keywords, category)
- `close()` → commits and closes the connection
- Context manager support (`__enter__` / `__exit__`)

**Acceptance Criteria**:
- [x] `python3 -c "from mcp_core.memory import MemoryStore; m = MemoryStore(); m.close()"` runs from `sysadmin/` and creates `.localai/memory.db`
- [x] Opening the database a second time does not error (idempotent schema)
- [x] `sqlite3 .localai/memory.db ".tables"` shows `lessons`, `pending_lessons`, `lessons_fts`

### Phase 1.03 — Lesson CRUD Operations

**Goal**: Add insert, get-by-id, list-all, update, and delete methods for the `lessons` table. Pure SQLite, fully testable without mocks.

**Deliverables**:
- `MemoryStore.insert_lesson(lesson_dict) → str` — returns generated ID
- `MemoryStore.get_lesson(lesson_id) → dict | None`
- `MemoryStore.list_lessons(category=None) → list[dict]`
- `MemoryStore.update_lesson(lesson_id, updates_dict)`
- `MemoryStore.delete_lesson(lesson_id)`
- FTS5 index automatically kept in sync via SQLite triggers or manual insert/delete into `lessons_fts`

**Acceptance Criteria**:
- [x] Insert a lesson, retrieve it by ID, fields match
- [x] `list_lessons()` returns all lessons; `list_lessons(category="sysadmin_bash")` filters correctly
- [x] Update a lesson's rule text, re-fetch confirms change
- [x] Delete a lesson, `get_lesson()` returns `None`

### Phase 1.04 — FTS5 Keyword Search

**Goal**: Add full-text keyword search over the lessons table using SQLite FTS5. This is the BM25 retrieval path used in Phase 4 for lesson injection.

**Deliverables**:
- `MemoryStore.search_lessons(query, top_k=3) → list[dict]` — FTS5 MATCH query ranked by BM25
- Results include a `rank` field (FTS5 BM25 score)
- Handles empty queries and no-match cases gracefully (returns `[]`)

**Acceptance Criteria**:
- [x] Insert 5 lessons with distinct keywords; search "heredoc EOF" returns the heredoc-related lesson ranked first
- [x] Search for a term that matches no lessons returns empty list
- [x] `top_k` parameter limits results correctly
- [x] Deleted lessons do not appear in search results

### Phase 1.05 — Unit Tests

**Goal**: Full pytest coverage for all Phase 1 deliverables. Tests use a temporary in-memory or `/tmp` database — no side effects on the real `.localai/memory.db`.

**Deliverables**:
- `sysadmin/tests/test_memory.py` with test cases covering:
  - Schema creation (idempotent)
  - Full CRUD lifecycle (insert → get → update → delete)
  - FTS5 search: relevance ranking, empty results, top_k limiting
  - Pending lessons table: insert and retrieve
  - Context manager protocol (`with MemoryStore(...) as m:`)

**Acceptance Criteria**:
- [x] `python3 -m pytest sysadmin/tests/test_memory.py -v` passes all tests from the `sysadmin/` directory
- [x] Tests create no persistent files (use temp directories or `:memory:` where possible)
- [x] At least 8 test cases covering the above scenarios

---

## Phase 2 — Lesson Staging (Pipeline Write Path) (~1 day)

> **Status**: ✅ **COMPLETE** — implemented 2026-08-28. See [`phase2_completion.md`](./phase2_completion.md) for the full completion report.

**Goal**: After any pipeline run where rework occurred (iteration > 1), stage a structured lesson in the pending queue — regardless of whether the run ultimately succeeded or failed. Failed runs carry equally valuable (often more actionable) anti-pattern signal.

### Pipeline Exit States & Staging Behavior

| Exit State | Trigger | `lesson_type` | Extraction Source |
|:---|:---|:---|:---|
| Pass on iteration 1 | `iterations == 1 AND approved` | — nothing staged — | — |
| **Success after rework** | `iterations > 1 AND approved` | `solved_pattern` | Reviewer final approval critique + diff |
| **Max retries exhausted** | `iterations == max AND not approved` | `hard_failure` | Last reviewer critique (what kept being flagged) |
| **Stuck loop abort** | `abort_reason` set + repeating critique | `intractable_pattern` | `reviewer_history` repeating signature (pre-structured, no extra Ollama call needed) |

> **Note on stuck-loop aborts**: The pipeline already accumulates `reviewer_history` as structured critique tuples. For `intractable_pattern` lessons, the repeating signature *is* the lesson — no additional Ollama extraction call is required, saving tokens and latency.

### Phase 2.01 — Pending Lesson CRUD on `MemoryStore`

**Goal**: Add methods to `memory.py` for staging, listing, and removing pending lessons. Pure data layer, no extraction logic.

**Deliverables**:
- `MemoryStore.stage_pending_lesson(lesson_dict) → str` — inserts into `pending_lessons`, returns generated ID
- `MemoryStore.list_pending_lessons() → list[dict]` — all pending items, ordered by `staged_at`
- `MemoryStore.get_pending_lesson(pending_id) → dict | None`
- `MemoryStore.delete_pending_lesson(pending_id)` — removes from pending queue
- `MemoryStore.promote_pending_lesson(pending_id, edits=None)` — moves from `pending_lessons` to `lessons` table (with optional field overrides), deletes the pending row

**Acceptance Criteria**:
- [x] Stage a lesson, list returns it, get returns it by ID
- [x] Promote moves the row from `pending_lessons` to `lessons` and deletes the pending row
- [x] Promote with `edits={"rule": "new text"}` applies the override to the promoted lesson
- [x] Delete removes from pending, does not affect `lessons` table

### Phase 2.02 — Lesson Extraction Prompt (LLM-Assisted)

**Goal**: Define the constrained extraction prompt that converts raw reviewer critique + pipeline context into a structured lesson JSON. Used for `solved_pattern` and `hard_failure` types.

**Deliverables**:
- `sysadmin/mcp_core/extraction.py` with `extract_lesson_from_critique(critique, task_file, prompt_content, model, lesson_type, outcome) → dict`
- Internally calls `transport.call_mcp("ollama_chat", ...)` with a constrained system prompt demanding JSON output
- Returns a validated dict with: `id`, `category`, `keywords`, `proposed_rule`, `reviewer_critique`, `task_file`, `lesson_type`, `outcome`
- Fallback: if Ollama returns unparseable JSON, constructs a best-effort lesson from raw critique text with `category="unknown"`

**Acceptance Criteria**:
- [x] With a mocked `transport.call_mcp` returning valid JSON, function returns a complete lesson dict
- [x] With a mocked transport returning garbage, fallback produces a valid (if coarse) lesson dict rather than crashing
- [x] Extraction prompt instructs the model to output *only* JSON, no preamble

### Phase 2.03 — Intractable Pattern Shortcut

**Goal**: For stuck-loop aborts, build a lesson directly from the pipeline's existing `reviewer_history` repeating signature — no Ollama call needed.

**Deliverables**:
- `sysadmin/mcp_core/extraction.py` gains `extract_lesson_from_stuck_loop(reviewer_history, abort_reason, task_file) → dict`
- Extracts keywords from the repeating critique tuple
- Sets `lesson_type="intractable_pattern"`, `outcome="aborted"`
- Constructs `proposed_rule` from the repeating critique points

**Acceptance Criteria**:
- [x] Given a `reviewer_history` with 3 identical critique tuples, produces a valid lesson dict
- [x] Does **not** call `transport.call_mcp` — zero Ollama invocations
- [x] `proposed_rule` captures the substance of the repeating critique

### Phase 2.04 — Pipeline Hook & Tests

**Goal**: Wire the extraction and staging logic into `pipeline.py` so lessons are staged automatically after every rework run.

**Deliverables**:
- `pipeline.py` `PipelineRunCommand.run()` updated: after `revision_loop()` returns, inspect `result` and call the appropriate staging path:
  - `iterations > 1 AND approved` → `extract_lesson_from_critique()` → `stage_pending_lesson()`
  - `iterations == max AND not approved AND no abort_reason` → `extract_lesson_from_critique()` → `stage_pending_lesson()`
  - `abort_reason` set → `extract_lesson_from_stuck_loop()` → `stage_pending_lesson()`
  - `iterations == 1 AND approved` → no-op
- Pipeline result dict gains `"rework_occurred": bool` and `"lesson_type": str | None`
- Terminal banner: `💡 1 new lesson staged in pending queue (type: solved_pattern)`
- Staging failures are logged but never block the pipeline

**Acceptance Criteria**:
- [x] `pipeline-run` with ≥2 iterations ending in approval → `solved_pattern` staged, banner printed
- [x] `pipeline-run` exhausting `max_retries` → `hard_failure` staged
- [x] `pipeline-run` stuck-loop abort → `intractable_pattern` staged without extra Ollama call
- [x] `pipeline-run` passing on iteration 1 → nothing staged, no banner
- [x] Staging error (e.g. disk full) logs a warning but pipeline still reports its normal result
- [x] Unit tests cover all four exit states with mocked transport (no live model needed)

---

## Phase 3 — Interactive Review CLI (Human Gate) (~1 day)

> **Status**: ✅ **COMPLETE** — implemented 2026-08-29. See [`phase3_completion.md`](./phase3_completion.md) for the full completion report.

**Goal**: `review-lessons` CLI command lets the developer batch-review all staged pending lessons interactively (Keep / Modify / Discard).

### Phase 3.01 — Lessons Markdown Writer

**Goal**: A utility that appends a promoted lesson to `ollama_update/lessons.md` in the canonical YAML-frontmatter format defined in `ai_memory_summary.md`.

**Deliverables**:
- `sysadmin/mcp_core/lessons_writer.py` with `append_lesson_to_markdown(lesson_dict, lessons_md_path) → None`
- Formats the lesson as a YAML frontmatter block (`---` delimited) followed by the rule text
- Appends to end of file (does not overwrite existing lessons)
- Handles first-lesson case (file has only the skeleton header)

**Acceptance Criteria**:
- [x] Appending a lesson to the skeleton `lessons.md` produces valid markdown with correct YAML frontmatter
- [x] Appending a second lesson does not corrupt the first
- [x] Output matches the format from `ai_memory_summary.md` §Pattern 1 (id, category, keywords, created, source_task)

### Phase 3.02 — CLI Command Registration

**Goal**: Create the `memory.py` command module and register `review-lessons` as a CLI subcommand.

**Deliverables**:
- `sysadmin/mcp_cli/commands/memory.py` — new file with `ReviewLessonsCommand` class using `@command` decorator
- `mcp_cli/commands/__init__.py` updated to import `memory` module
- Command wired into argparse: `python3 sysadmin/mcp_client.py review-lessons`
- When no pending lessons exist, prints `✅ No pending lessons to review.` and exits cleanly

**Acceptance Criteria**:
- [x] `python3 sysadmin/mcp_client.py --help` lists `review-lessons` in available commands
- [x] `python3 sysadmin/mcp_client.py review-lessons` with empty pending queue prints the clean message and exits 0

### Phase 3.03 — Interactive Review Loop

**Goal**: The core interactive terminal UI that iterates over pending lessons and prompts the developer for action.

**Deliverables**:
- `ReviewLessonsCommand.run()` loads all pending lessons via `MemoryStore.list_pending_lessons()`
- For each item, prints a formatted review card showing: task file, lesson_type, reviewer critique, proposed rule, keywords
- Prompts for action: `[k] Keep`, `[m] Modify`, `[d] Discard`, `[s] Skip`
- **Keep**: calls `MemoryStore.promote_pending_lesson()` + `append_lesson_to_markdown()`
- **Modify**: prompts for new rule text and/or keywords, then promotes with edits
- **Discard**: calls `MemoryStore.delete_pending_lesson()`
- **Skip**: moves to next item without action
- Prints summary at end: `Kept: 2 | Modified: 1 | Discarded: 1 | Skipped: 0`

**Acceptance Criteria**:
- [x] Interactive prompts render correctly in terminal with readable formatting
- [x] Keep action results in the lesson appearing in both `lessons.md` and `memory.db` active table
- [x] Modify action allows editing rule text before promotion
- [x] Discard removes from pending without affecting active lessons
- [x] Summary counts are accurate

### Phase 3.04 — Tests

**Goal**: Unit tests for the markdown writer and review flow (with stdin mocking for interactive prompts).

**Deliverables**:
- `sysadmin/tests/test_lessons_writer.py` — tests for `append_lesson_to_markdown()`
- `sysadmin/tests/test_review_lessons.py` — tests for the review command with mocked `input()` calls
- Tests verify: markdown format, CRUD side effects, summary counts

**Acceptance Criteria**:
- [x] All tests pass with `python3 -m pytest sysadmin/tests/test_lessons_writer.py sysadmin/tests/test_review_lessons.py -v`
- [x] No tests require live terminal interaction (all use mocked stdin)
- [x] At least 6 test cases across both files

---

## Phase 4 — Lesson Injection (Pipeline Read Path) (~1–2 days)

**Goal**: Before the Author's first iteration, query the memory store for lessons relevant to the current task prompt and inject the top-K into the Author's context.

### Phase 4.01 — Injection Formatter

**Goal**: A utility that takes a list of lesson dicts and renders them as a markdown section suitable for prepending to the Author prompt.

**Deliverables**:
- `sysadmin/mcp_core/injection.py` with `format_lessons_for_prompt(lessons: list[dict]) → str`
- Output is a `### Relevant Lessons from Past Runs` markdown section
- Each lesson rendered as a numbered block with rule text, category, and keywords
- Returns empty string when the lessons list is empty (no section header injected)

**Acceptance Criteria**:
- [ ] 3 lessons produce a readable markdown section with 3 numbered blocks
- [ ] Empty list returns `""`
- [ ] Output contains no raw JSON — human-readable rule text only

### Phase 4.02 — Embedding Model Setup

**Goal**: Pull the `nomic-embed-text` model and verify it can produce embeddings via the Ollama API.

**Deliverables**:
- `ollama pull nomic-embed-text` executed and verified
- `sysadmin/mcp_core/embeddings.py` with `get_embedding(text, model="nomic-embed-text") → list[float]`
- Internally calls `ollama.embeddings()` HTTP API (or `transport.call_mcp` if an embedding tool exists)
- Returns a float vector; raises on failure

**Acceptance Criteria**:
- [ ] `ollama list` shows `nomic-embed-text`
- [ ] `get_embedding("test sentence")` returns a list of floats with length > 0
- [ ] Function works from within `sysadmin/` import path

### Phase 4.03 — Vector Search with `sqlite-vec`

**Goal**: Add vector similarity search to `MemoryStore` using `sqlite-vec`. If installation fails, this sub-phase is deferred and Phase 4.04 ships with FTS5-only search.

**Deliverables**:
- `pip install sqlite-vec` in the sysadmin venv
- `MemoryStore` gains an `embeddings` column (BLOB) in the `lessons` table
- `MemoryStore.insert_lesson()` updated: if embedding is provided, store it
- `MemoryStore.search_lessons_vector(query_embedding, top_k=3) → list[dict]` — cosine similarity via `sqlite-vec`
- `MemoryStore.search_lessons_hybrid(query_text, query_embedding, top_k=3) → list[dict]` — combines FTS5 BM25 + vector scores

**Acceptance Criteria**:
- [ ] Insert 5 lessons with embeddings; vector search for a related embedding returns the correct lesson first
- [ ] Hybrid search combines both signals (a lesson matching both keyword and vector scores outranks one matching only one)
- [ ] If `sqlite-vec` is not importable, `search_lessons_hybrid` degrades gracefully to FTS5-only

### Phase 4.04 — Pipeline Injection Hook & Tests

**Goal**: Wire the search and injection into `pipeline.py` so the Author prompt is enriched with relevant lessons on every run.

**Deliverables**:
- `pipeline.py` `revision_loop()` updated: before iteration 1, call `search_lessons` (or `search_lessons_hybrid`) with the prompt content as query
- Prepend formatted lessons to `current_prompt` via `format_lessons_for_prompt()`
- Track `injected_lessons` (list of lesson IDs) in the pipeline result dict
- Terminal banner: `📚 Injected 3 relevant lessons from memory`
- When no lessons match, no injection and no banner

**Acceptance Criteria**:
- [ ] A lesson about "heredoc delimiters" is retrieved and injected when the task prompt mentions "heredoc"
- [ ] Pipeline result includes `injected_lessons` list with matching IDs
- [ ] With zero lessons in the store, pipeline runs identically to current behavior (no regression)
- [ ] Unit tests: insert lessons, mock pipeline, verify injection appears in Author prompt

---

## Phase 5 — Retrieval Telemetry & Attribution (~1 day)

**Goal**: Track whether injected lessons actually prevented rework, and decay ineffective lessons out of top-K results over time.

### Phase 5.01 — Retrieval Counter Updates

**Goal**: After every pipeline run, increment `retrieval_count` for each lesson that was injected into the Author prompt.

**Deliverables**:
- `MemoryStore.increment_retrieval_count(lesson_ids: list[str])` — batch increment
- Called from `pipeline.py` after `revision_loop()` completes, using the `injected_lessons` list from Phase 4.04
- No-op when `injected_lessons` is empty

**Acceptance Criteria**:
- [ ] After a pipeline run injecting lessons A and B, both have `retrieval_count += 1`
- [ ] Running with no injected lessons does not modify any rows
- [ ] Counter survives across MemoryStore sessions (persisted to disk)

### Phase 5.02 — Attribution Logic (Blame / Innocent / Credit)

**Goal**: After a pipeline run, determine whether each injected lesson helped, was irrelevant, or was actively harmful.

**Deliverables**:
- `sysadmin/mcp_core/attribution.py` with `attribute_lessons(injected_lessons, pipeline_result, reviewer_critique) → dict[str, str]`
- Returns a mapping of `lesson_id → "credited" | "blamed" | "innocent"`
- Logic:
  - **Pass on iteration 1** (no rework): all injected lessons → `"credited"`, `prevented_rework_count += 1`
  - **Rework occurred**: compare each lesson's keywords against the reviewer critique keywords
    - Overlap found → `"blamed"`, `ineffective_count += 1`
    - No overlap → `"innocent"`, no counter change
- `MemoryStore.update_telemetry(lesson_id, field, increment=1)` — generic counter update

**Acceptance Criteria**:
- [ ] Iteration-1 pass credits all injected lessons
- [ ] Lesson with keyword "heredoc" is blamed when critique mentions "heredoc"
- [ ] Lesson with keyword "ansible" is innocent when critique is about "heredoc"
- [ ] Counters reflect the attribution correctly in the database

### Phase 5.03 — Dynamic Ranking Suppression & Tests

**Goal**: Modify `search_lessons` to weight results by their utility score, suppressing frequently-retrieved but ineffective lessons.

**Deliverables**:
- `MemoryStore.search_lessons()` updated: final score = `bm25_score × ((prevented + 1) / (retrieved + 2))`
- Lessons with high retrieval count and zero preventions decay below the top-K threshold
- `search_lessons_hybrid()` applies the same suppression factor to the combined score

**Acceptance Criteria**:
- [ ] A lesson retrieved 10 times with 0 preventions ranks lower than a lesson retrieved 2 times with 1 prevention (given similar BM25 scores)
- [ ] A brand-new lesson (0 retrieved, 0 prevented) gets a neutral score of `1 × (1/2) = 0.5` multiplier — not penalized
- [ ] Unit tests with synthetic counters verify ranking order changes

---

## Phase 6 — Audit, Promotion & System Rules (~1–2 days)

**Goal**: `audit-lessons` CLI command clusters related lessons, promotes recurring patterns to `SYSTEM_RULES.md`, and flags low-utility lessons for cleanup.

### Phase 6.01 — Lesson Clustering Engine

**Goal**: Group related lessons by category, keyword overlap, and retrieval frequency to identify promotion candidates.

**Deliverables**:
- `sysadmin/mcp_core/audit.py` with `cluster_lessons(lessons: list[dict], min_cluster_size=3) → list[dict]`
- Each cluster is a dict: `{"keywords": [...], "category": str, "lesson_ids": [...], "count": int}`
- Clustering logic: lessons sharing ≥2 keywords or same category with ≥`min_cluster_size` members form a cluster
- Sorted by cluster size descending

**Acceptance Criteria**:
- [ ] 5 lessons about "heredoc" / "EOF" / "delimiter" cluster together
- [ ] 2 unrelated lessons do not form a cluster at `min_cluster_size=3`
- [ ] Pure function, no database or file I/O — takes a list, returns a list

### Phase 6.02 — `SYSTEM_RULES.md` Writer

**Goal**: A utility that appends a promoted universal rule to `sysadmin/prompts/SYSTEM_RULES.md` with provenance metadata.

**Deliverables**:
- `sysadmin/mcp_core/rules_writer.py` with `append_system_rule(rule_text, source_lesson_ids, rules_md_path) → None`
- Format: numbered rule block with `**Promoted**: <date>`, `**Source Lessons**: <ids>`, followed by rule text
- Auto-increments rule number based on existing rules in the file

**Acceptance Criteria**:
- [ ] Appending to the skeleton `SYSTEM_RULES.md` produces a correctly numbered `### Rule #1` block
- [ ] Appending a second rule produces `### Rule #2`
- [ ] Provenance includes date and source lesson IDs

### Phase 6.03 — Low-Utility Lesson Flagging

**Goal**: Identify lessons that are retrieved frequently but never prevent rework, flagging them for cleanup.

**Deliverables**:
- `sysadmin/mcp_core/audit.py` gains `flag_low_utility(lessons: list[dict], min_retrievals=5, max_prevention_ratio=0.3) → list[dict]`
- Returns lessons where `retrieval_count >= min_retrievals` and `prevented_rework_count / retrieval_count < max_prevention_ratio`
- Each flagged lesson includes computed `prevention_ratio` and `utility_score`

**Acceptance Criteria**:
- [ ] Lesson with 8 retrievals and 0 preventions is flagged
- [ ] Lesson with 8 retrievals and 4 preventions (50%) is not flagged
- [ ] Lesson with 3 retrievals and 0 preventions is not flagged (below `min_retrievals` threshold)

### Phase 6.04 — Interactive Audit CLI (`audit-lessons`)

**Goal**: Register `audit-lessons` CLI command with interactive promotion/cleanup flow.

**Deliverables**:
- `sysadmin/mcp_cli/commands/memory.py` gains `AuditLessonsCommand` with `@command` decorator
- Loads all active lessons, runs clustering and low-utility flagging
- For each cluster: `[p] Promote to SYSTEM_RULES.md`, `[m] Modify rule before promoting`, `[k] Keep as episodic`, `[d] Discard cluster`
- **Promote**: calls `append_system_rule()`, archives source lessons to `ollama_update/lessons_archive.md`, removes from active `lessons` table
- For each low-utility lesson: `[d] Delete`, `[m] Rewrite keywords/rule`, `[s] Skip`
- Prints summary at end

**Acceptance Criteria**:
- [ ] `python3 sysadmin/mcp_client.py audit-lessons` runs and displays clusters
- [ ] Promoted rule appears in `SYSTEM_RULES.md` with correct numbering and provenance
- [ ] Archived lessons move to `lessons_archive.md` and are removed from active table
- [ ] Low-utility lessons are flagged with stats (retrieval count, prevention ratio)

### Phase 6.05 — Pipeline Auto-Load of System Rules & Tests

**Goal**: Make `pipeline.py` automatically include `SYSTEM_RULES.md` content in both the Author and Reviewer system prompts.

**Deliverables**:
- `pipeline.py` updated: on `revision_loop()` entry, read `sysadmin/prompts/SYSTEM_RULES.md` if it exists
- Prepend rules content to Author prompt as `### Universal System Rules` section
- Include rules in the reviewer's `_build_review_prompt()` as an additional verification reference
- If `SYSTEM_RULES.md` is empty or missing, no-op (no regression)

**Acceptance Criteria**:
- [ ] With a rule in `SYSTEM_RULES.md`, both Author and Reviewer prompts contain the rule text
- [ ] With empty `SYSTEM_RULES.md`, pipeline behavior is unchanged from current
- [ ] Unit tests verify rules are included in both prompts

---

## Phase 7 — Trajectory Recording & Wiki Dashboard (~2 days)

**Goal**: Record rejected/approved script pairs for future fine-tuning data, and generate a human-readable wiki dashboard of memory health.

### Phase 7.01 — Trajectory Recorder (Pipeline Hook)

**Goal**: After any multi-iteration pipeline run, record a trajectory entry capturing the rejected and approved script versions.

**Deliverables**:
- `sysadmin/mcp_core/trajectories.py` with `record_trajectory(pipeline_result, prompt_content, trajectories_path) → str`
- Appends a single JSON line to `sysadmin/data/trajectories.jsonl`
- Record includes: `id`, `timestamp`, `task_file`, `injected_lessons`, `reviewer_critique`, `iterations`, `outcome`
- Hook in `pipeline.py`: called alongside lesson staging (Phase 2.04) for any run with `iterations > 1`

**Acceptance Criteria**:
- [ ] After a 2-iteration pipeline run, `trajectories.jsonl` gains one new line
- [ ] Record contains valid JSON parseable by `json.loads()`
- [ ] Iteration-1 passes do not produce trajectory records

### Phase 7.02 — Tiered Schema (Inline vs. Diff+Ref)

**Goal**: For large scripts, store compact diffs instead of full verbatim code to prevent `trajectories.jsonl` bloat.

**Deliverables**:
- `record_trajectory()` updated with tiered logic:
  - **Tier 1** (scripts <150 lines): `rejected` and `chosen` stored inline as strings, `payload_type="inline"`
  - **Tier 2** (scripts ≥150 lines): `diff` + `focused_snippet` stored inline, verbatim files offloaded to `sysadmin/data/raw_trajectories/<id>/`, `payload_type="diff_and_ref"`
- `focused_snippet`: ±15 lines around the failure point indicated by the reviewer critique
- `diff`: unified diff between rejected and chosen versions

**Acceptance Criteria**:
- [ ] A 50-line script stores inline (`payload_type="inline"`, `rejected` and `chosen` present)
- [ ] A 200-line script stores diff+ref (`payload_type="diff_and_ref"`, `diff` and `focused_snippet` present, raw files in subdirectory)
- [ ] Diff is a valid unified diff format

### Phase 7.03 — Wiki Index Generator

**Goal**: Generate `ollama_update/wiki/index.md` — a categorized catalog of all active lessons.

**Deliverables**:
- `sysadmin/mcp_core/wiki.py` with `generate_index(lessons: list[dict], output_path) → None`
- Groups lessons by category into markdown tables
- Each row: lesson ID, keywords, rule summary (truncated), source task, created date
- Links lesson IDs for Obsidian cross-referencing

**Acceptance Criteria**:
- [ ] 10 lessons across 3 categories produce a markdown file with 3 tables
- [ ] Empty lesson list produces a valid file with "No lessons recorded" message
- [ ] Output is valid markdown

### Phase 7.04 — Wiki Dashboard Generator

**Goal**: Generate `ollama_update/wiki/dashboard.md` — a telemetry snapshot with retrieval leaderboard and health indicators.

**Deliverables**:
- `sysadmin/mcp_core/wiki.py` gains `generate_dashboard(lessons: list[dict], output_path) → None`
- Sections: Top-retrieved lessons, highest-utility lessons, promotion candidates (clusters), low-utility flags
- Includes computed stats: retrieval_count, prevention_ratio, utility_score
- `generate_log(events: list[dict], output_path) → None` — appends chronological entries to `ollama_update/wiki/log.md`

**Acceptance Criteria**:
- [ ] Dashboard with 10 lessons produces readable leaderboard tables
- [ ] Log entries are append-only (running twice doesn't overwrite previous entries)
- [ ] Valid markdown viewable in Obsidian

### Phase 7.05 — `compile-wiki` CLI & Tests

**Goal**: Register `compile-wiki` CLI command that runs all wiki generators in one pass.

**Deliverables**:
- `sysadmin/mcp_cli/commands/memory.py` gains `CompileWikiCommand` with `@command` decorator
- Loads all lessons from `MemoryStore`, calls `generate_index()`, `generate_dashboard()`, `generate_log()`
- Creates `ollama_update/wiki/` directory if it doesn't exist
- Prints summary: `📚 Wiki compiled: index.md (10 lessons), dashboard.md, log.md`

**Acceptance Criteria**:
- [ ] `python3 sysadmin/mcp_client.py compile-wiki` generates all three files
- [ ] Running twice updates files without corruption
- [ ] Unit tests verify output file contents with synthetic lesson data

---

## Dependency Graph

```
Phase 1 (Schema)
  ├── Phase 2 (Staging / Write Path)
  │     └── Phase 3 (Review CLI)
  ├── Phase 4 (Injection / Read Path)
  │     └── Phase 5 (Telemetry)
  │           └── Phase 6 (Audit & Promotion)
  └──────────────── Phase 7 (Trajectories & Wiki)
```

Phases 2 and 4 can run in parallel after Phase 1.
Phase 7 can begin after Phase 2 (trajectory recording) but the wiki needs Phase 5 data to be meaningful.

---

## Runtime Prerequisites

| Dependency | Status | Action |
|:---|:---|:---|
| Python 3.12 | ✅ Available | — |
| SQLite 3.45 (built-in) | ✅ Available | — |
| SQLite FTS5 | ✅ Built-in since 3.9 | Verify: `python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(x)')"` |
| `nomic-embed-text` | ❌ Not pulled | `ollama pull nomic-embed-text` (Phase 4) |
| `sqlite-vec` | ❌ Not installed | `pip install sqlite-vec` (Phase 4, or defer to 4b) |
| Ollama API | ✅ Running | Models available for extraction calls |
