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
Evaluate candidate Ollama embedding models on a representative sample of lesson texts to select the model that provides the best quality/performance tradeoff for short-text semantic similarity.

### Why
Lesson rules are short texts (typically 10-40 words). Embedding models optimized for long documents may not perform well. Model dimensionality affects storage footprint and search performance. The choice is foundational — changing models later requires re-embedding the entire corpus.

### Design Notes

**Candidate models to evaluate** (available via `ollama pull`):
- `nomic-embed-text` — 768 dimensions, general-purpose, good short-text performance
- `mxbai-embed-large` — 1024 dimensions, higher quality but larger storage
- `all-minilm` — 384 dimensions, smallest footprint, decent quality
- `snowflake-arctic-embed` — multiple sizes available

**Evaluation protocol**:
1. Pull each candidate model via the local-ollama MCP (`ollama_pull_model`).
2. Generate embeddings for a sample of 10-15 lesson rules covering diverse categories.
3. Compute pairwise cosine similarity matrices.
4. Evaluate against known ground truth:
   - **True duplicates** (lexically similar lessons from the Stage 1 audit) should have cosine similarity > 0.85.
   - **Semantic duplicates** (same meaning, different words — manually curated test pairs) should have cosine similarity > 0.70.
   - **Unrelated lessons** (different categories, different topics) should have cosine similarity < 0.40.
5. Measure generation latency per lesson (single inference call).
6. Record storage footprint per lesson (dimensions × 4 bytes per float32).

**Selection criteria**: Prioritize quality of semantic similarity discrimination, then latency, then storage. The model must run locally on the available hardware without GPU memory issues.

### Acceptance Criteria
- At least 3 models are benchmarked.
- A benchmark results document is produced showing similarity matrices, latency, and storage comparisons.
- One model is selected with documented rationale.
- The selected model is pulled and available via `ollama list`.

---

## Step 2: Build the Embedding Generation Function

### What
Create a function that takes lesson text and returns a dense vector embedding using the selected Ollama model.

### Where
- `sysadmin/mcp_core/embeddings.py` (new file).

### Design Notes

**Function signature**: `embed_text(text: str, model: str = EMBEDDING_MODEL) -> Optional[list[float]]`

**Configuration**:
- `EMBEDDING_MODEL` constant (set to the model selected in Step 1).
- `EMBEDDING_DIMENSIONS` constant (must match the model's output dimensionality).
- The Ollama host URL should come from the environment (`$OLLAMA_HOST`) or a default.

**Implementation approach**:
- Use the Ollama API's `/api/embed` endpoint (or the equivalent MCP tool) to generate embeddings.
- Normalize the input text before embedding (strip whitespace, collapse runs). This is different from `normalize_lesson_rule()` which strips punctuation — the embedding model benefits from natural text with punctuation.
- Handle failure gracefully: return `None` if the Ollama server is unreachable or the model is not loaded. Never raise on embedding failure — embeddings are an enhancement, not a requirement.

**Batching**: Include a `embed_texts(texts: list[str]) -> list[Optional[list[float]]]` variant for efficient batch embedding during backfill. If the Ollama API supports batch embedding, use it. Otherwise, iterate with a simple loop.

### Acceptance Criteria
- `embed_text("Always quote variables in shell scripts")` returns a list of floats with the correct dimensionality.
- `embed_text("")` returns `None`.
- When Ollama is unreachable, the function returns `None` without raising.
- `embed_texts()` returns correct results for a batch of 5 inputs.

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

## Step 5: Embedding Health Monitoring

### What
Add observability for embedding coverage and staleness so operators can detect when embeddings are missing or potentially stale.

### Where
- `sysadmin/mcp_core/memory.py`: Add a health/status method.
- `sysadmin/mcp_cli/commands/memory.py`: Surface in CLI output (e.g., `localai audit-lessons` or a new subcommand).

### Design Notes

**Health metrics**:
- `total_lessons`: Count of active lessons.
- `embedded_lessons`: Count of lessons with non-NULL embeddings.
- `coverage_pct`: `embedded / total * 100`.
- `null_embeddings`: List of lesson IDs with NULL embeddings.
- `model_name`: The configured embedding model (so operators know what model generated the stored vectors).
- `embedding_dimensions`: The expected dimensionality.

**Staleness detection**: If the configured `EMBEDDING_MODEL` changes (e.g., operator switches from `nomic-embed-text` to `mxbai-embed-large`), all existing embeddings are effectively stale because they were generated by a different model. Store the model name used for embedding generation as metadata (either in a new `embedding_model` column or a config table) so staleness can be detected.

**Display**: Surface in `localai audit-lessons` output alongside the existing low-utility and cluster analysis.

### Acceptance Criteria
- Health check reports accurate coverage percentage.
- Missing embeddings are listed by lesson ID.
- If the embedding model changes, a warning is displayed indicating existing embeddings may be stale.

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
