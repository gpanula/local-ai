# Stage 2A Implementation Plan: Embedding Infrastructure

> **Parent**: [stages-overview.md](stages-overview.md)
> **Prerequisites**: [Stage 1](stage-1-implementation-plan.md) completed (lexical dedup lifecycle working, stale embeddings NULLed during compaction)
> **Estimated Scope**: ~7 steps across 3-4 source files + 2 test files

---

## Objective

Build the embedding generation and lifecycle pipeline so every active lesson has a dense vector representation stored in SQLite via `sqlite-vec`. This stage provides the foundation for hybrid retrieval (Stage 2B) and semantic deduplication (Stage 3).

---

## Current State of Embedding Infrastructure

The schema and search functions already exist but are unfed:
- `lessons` table has an `embeddings BLOB` column (added in migration).
- `search_lessons_vector()` in `memory.py` queries `vec_distance_cosine()` when `sqlite-vec` is available.
- `search_lessons_hybrid()` in `memory.py` merges BM25 + vector scores.
- `_serialize_embedding()` / `_deserialize_embedding()` handle float32 BLOB conversion.
- **Missing**: No code anywhere generates embeddings. All `embeddings` values are NULL.

---

## Step 1: Benchmark & Select Local Ollama Embedding Model

### What
Empirically verify the performance and quality of the resident local Ollama embedding model (`nomic-embed-text:latest`) on representative lesson texts, confirming suitability for short-text semantic similarity before committing to the schema.

### Why
Lesson rules are short texts (typically 10-40 words). The model must provide strong discrimination between true semantic equivalents and unrelated rules without consuming prohibitive VRAM.

### Design Notes

**Resident Model Status**:
- `nomic-embed-text:latest` (137M parameters, 768 dimensions, F16 quantization, ~260MB VRAM footprint) is **already installed locally** in the Ollama instance.
- Because it is lightweight (0.26 GB) and specifically pre-trained with 8192 context window and high clustering accuracy for short texts, it serves as the primary candidate.
- Fallback candidates (e.g. `mxbai-embed-large` [1024d] or `all-minilm` [384d]) will only be evaluated if `nomic-embed-text` fails discrimination thresholds.

**Verification protocol**:
1. Execute embedding generation via native MCP / Ollama embedding endpoints for 10-15 curated lesson rules.
2. Compute pairwise cosine similarity matrices across:
   - **True duplicates** (e.g. `lesson-20260918-05` and `lesson-20260929-01`): Target cosine similarity $\ge 0.80$.
   - **Same-domain, different-intent rules**: Target cosine similarity between $0.45$ and $0.70$.
   - **Completely unrelated rules** (e.g. Docker Orchestration vs Bash Tracing): Target cosine similarity $< 0.40$.
3. Measure single-call and batch latency per lesson (target < 50ms per item on local hardware).
4. Confirm 768 dimensions float32 footprint (~3 KB per lesson BLOB).

### Acceptance Criteria
- `nomic-embed-text:latest` discrimination verified against ground-truth pairs.
- Verification findings recorded (cosine similarity matrix and latency measurements).
- Selected model and dimensionality (`768`) confirmed for `MemoryStore` integration.

---

## Step 2: Build the Embedding Generation Function & Native MCP Tool

### What
1. Build `sysadmin/mcp_core/embeddings.py` providing `embed_text()` and batch `embed_texts()` functions.
2. Expose the native MCP tool `ollama_embed` in `sysadmin/mcp_ollama/server.py` to ensure IDE agents interact with embeddings through native MCP calling (satisfying `AGENTS.md` Rule 7).

### Where
- `sysadmin/mcp_core/embeddings.py` (new core module).
- `sysadmin/mcp_ollama/server.py` (tool registration & schema).
- `sysadmin/mcp_ollama/ollama_embed.json` (MCP tool schema).

### Design Notes

**Function signature**:
```python
def embed_text(text: str, model: str = EMBEDDING_MODEL) -> Optional[list[float]]: ...
def embed_texts(texts: list[str], model: str = EMBEDDING_MODEL) -> list[Optional[list[float]]]: ...
```

**Configuration**:
- `EMBEDDING_MODEL = "nomic-embed-text:latest"`
- `EMBEDDING_DIMENSIONS = 768`
- Resolved deterministically via `$OLLAMA_HOST` (defaulting to `http://127.0.0.1:11434`).

**Implementation & API Protocol**:
- Use Ollama's modern `/api/embed` batch endpoint (replacing deprecated `/api/embeddings`).
- Strip extraneous whitespace while preserving natural punctuation (contrast with lexical `normalize_lesson_rule()` which strips symbols).
- Non-blocking error handling: Return `None` if Ollama is unreachable, model is unpulled, or payload is empty. Never raise unhandled exceptions into the caller.

**Native MCP Tool (`ollama_embed`)**:
- Registers in `server.py` with arguments `{"texts": list[str], "model": Optional[str]}`.
- Allows external agents and subagents to request embeddings without executing curl or raw subshell scripts.

### Acceptance Criteria
- `embed_text("Always quote variables in shell scripts")` returns a list of 768 floats.
- `embed_texts()` processes batch inputs in a single round-trip.
- `embed_text("")` returns `None`.
- `ollama_embed` tool callable via `call_mcp_tool('local-ollama', 'ollama_embed', ...)`.
- Graceful `None` fallback when the Ollama daemon is offline.

---

## Step 3: Add Lifecycle Hooks to MemoryStore

### What
Integrate embedding generation into the lesson lifecycle so embeddings are automatically created on insert and updated on rule changes.

### Where
- `sysadmin/mcp_core/memory.py`: Modify `insert_lesson()`, `update_lesson()`, and add an embedding refresh method.

### Design Notes

**On `insert_lesson()`**:
- After inserting the lesson, if the lesson dict does not already contain an `embeddings` value, call `embed_text(rule)` and store the result.
- If embedding generation fails (returns `None`), the lesson is still inserted with `embeddings=NULL`. This maintains the current behavior where embeddings are optional.

**On `update_lesson()`**:
- If `rule` is in the updated fields, regenerate the embedding for the new rule text.
- If embedding generation fails, set `embeddings=NULL` (invalidation fallback from Stage 1 is preserved).
- Add `embeddings` to the allowed update fields in `LESSON_COLUMNS` — or handle it separately since it's not user-editable.

**Explicit methods**:
- `refresh_embedding(lesson_id: str) -> bool`: Regenerate and store the embedding for a single lesson. Returns `True` on success.
- `refresh_all_embeddings(batch_size: int = 10) -> tuple[int, int]`: Regenerate embeddings for all lessons with `embeddings IS NULL`. Returns `(success_count, failure_count)`. This is the backfill method.

**Graceful degradation**: If the embedding module is not importable (e.g., missing `requests` or Ollama not configured), all embedding operations should no-op silently. The system must remain fully functional without embeddings.

### Acceptance Criteria
- Inserting a new lesson automatically generates and stores an embedding (when Ollama is available).
- Updating a lesson's rule text regenerates the embedding.
- `refresh_embedding()` successfully regenerates a single lesson's embedding.
- `refresh_all_embeddings()` processes all NULL-embedding lessons.
- When Ollama is unavailable, all lesson operations still work — embeddings are just NULL.

---

## Step 4: Backfill Existing Lesson Embeddings

### What
Generate embeddings for all existing active lessons that currently have `embeddings=NULL`.

### Where
- Invoked via `MemoryStore.refresh_all_embeddings()` or a CLI command.

### Design Notes

**Execution approach**: Use the `refresh_all_embeddings()` method from Step 3. This should be runnable via:
- Direct Python call: `MemoryStore().refresh_all_embeddings()`
- CLI integration: Consider adding a `localai embed-lessons` subcommand or integrating into `localai-compact` as a `--embed` flag.

**Progress reporting**: For the ~28 distinct active lessons (post-Stage 1 compaction), backfill should complete in under 2 minutes. Log progress: `"Embedded 15/28 lessons..."`.

**Error handling**: If embedding fails for specific lessons (e.g., unusually long text, model error), log the failure and continue. Report the total success/failure counts at the end.

### Acceptance Criteria
- After backfill, `SELECT COUNT(*) FROM lessons WHERE embeddings IS NULL` returns 0 (assuming Ollama was available for all).
- Backfill is idempotent — running it again on fully-embedded lessons is a no-op or quick skip.
- Progress is logged to stdout.
- Any failures are logged with the lesson ID and error.

---

## Step 5: Embedding Health Monitoring & TUI Observability

### What
Add observability for embedding coverage and staleness, surfacing embedding state across both CLI tools and the Consolidation TUI (`CompactionTUIApp`).

### Where
- `sysadmin/mcp_core/memory.py`: Add `get_embedding_health()` status method.
- `sysadmin/mcp_cli/commands/memory.py`: Surface in `localai audit-lessons` and `localai-compact` CLI output.
- `sysadmin/lessons_tui/widgets/cluster_detail.py`: Surface vector embedding badge and dimension info.
- `sysadmin/lessons_tui/compact_app.py`: Add `[EMBEDDED]` / `[NO-VEC]` badges and `e` keybinding to trigger on-demand embedding.

### Design Notes

**Health metrics**:
- `total_lessons`: Count of active lessons.
- `embedded_lessons`: Count of lessons with non-NULL embeddings.
- `coverage_pct`: `embedded / total * 100`.
- `null_embeddings`: List of lesson IDs with NULL embeddings.
- `model_name`: The configured embedding model (e.g. `nomic-embed-text:latest`).
- `embedding_dimensions`: The expected dimensionality (768).

**Staleness detection**:
- Store the generating model name in the database metadata table (`schema_meta` or `embedding_model` column).
- If the configured `EMBEDDING_MODEL` changes, `get_embedding_health()` flags a `STALE_MODEL` warning.
- Provide a `--reindex` flag in `localai-embed-lessons` to re-embed all lessons upon model migration.

**Consolidation TUI Integration**:
- In `CompactionTUIApp` detail pane, display an indicator: `[EMBEDDED: 768d]` or `[NO-VEC: NULL]`.
- Pressing `e` on an unembedded candidate lesson stages or triggers immediate background embedding via `refresh_embedding()`.

### Acceptance Criteria
- Health check reports accurate coverage percentage and model metadata.
- Missing embeddings are listed by lesson ID in audit output.
- If the embedding model changes, a warning is displayed indicating existing embeddings are stale.
- TUI shows `[EMBEDDED]` status in the lesson detail pane.

---

## Step 6: Validate Vector Search Functions

### What
Verify that the existing `search_lessons_vector()` and `search_lessons_hybrid()` functions in `memory.py` work correctly with real embeddings.

### Why
These functions have been in the codebase since Phase 1 but have never been exercised with real data (all embeddings were NULL). They may have bugs that only surface with actual vector data.

### Where
- `sysadmin/tests/test_memory.py`: Add vector search tests.

### Design Notes

**Test approach**: Use a test fixture that:
1. Creates an in-memory MemoryStore.
2. Inserts 5 lessons with pre-computed embedding vectors (hardcoded float lists, not generated via Ollama — tests must not depend on external services).
3. Queries `search_lessons_vector()` with a query vector similar to one of the lessons.
4. Asserts the most similar lesson is ranked first.
5. Queries `search_lessons_hybrid()` with both text and vector query.
6. Asserts hybrid results combine both signals.

**Edge cases to test**:
- Query when some lessons have NULL embeddings (those should be skipped).
- Query when `sqlite-vec` is not available (should return empty list).
- Empty query embedding (should return empty list).

### Acceptance Criteria
- Vector search returns lessons ranked by cosine similarity (closest first).
- Hybrid search returns results that combine FTS5 and vector scores.
- Lessons with NULL embeddings are excluded from vector search but included in FTS search.
- All tests pass with and without `sqlite-vec` available.

---

## Step 7: Commit & Documentation

### What
Commit all Stage 2A changes with appropriate gitmoji conventional commits and update documentation.

### Where
- Feature branch (branched from Stage 1 completion).
- Update `docs/lesson_memory_update/` with any implementation notes.

### Design Notes

**Commit strategy**: Separate commits for:
1. Embedding generation module (`embeddings.py`).
2. MemoryStore lifecycle hooks.
3. CLI integration (if added).
4. Test suite additions.
5. Backfill execution results.

**Documentation**: Update the stages overview doc to mark Stage 2A as complete and record the selected embedding model and its rationale.

### Acceptance Criteria
- All new code is committed on a feature branch.
- Full test suite passes.
- Embedding coverage is 100% on the production database.
- The selected embedding model and rationale are documented.
