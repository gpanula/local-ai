# Stage 2B Implementation Plan: Hybrid Retrieval Upgrade

> **Parent**: [stages-overview.md](stages-overview.md)
> **Prerequisites**: [Stage 2A](stage-2a-implementation-plan.md) completed (all active lessons have embeddings, vector search validated)
> **Estimated Scope**: ~6 steps across 3 source files + 2 test files

---

## Objective

Wire hybrid search (BM25 keyword matching + vector cosine similarity) into the lesson retrieval pipeline as the primary search path. This improves retrieval quality by surfacing lessons that are semantically relevant even when they don't share exact keywords with the query.

---

## Current State

- `collect_relevant_lessons()` in `pipeline.py` calls `memory_store.search_lessons()` (FTS5/BM25 only).
- `search_lessons_hybrid()` exists in `memory.py` but is never called from the pipeline.
- After Stage 2A, all active lessons have embeddings, so hybrid search can produce results.

---

## Step 1: Build Query Embedding Pipeline

### What
Create a function that generates an embedding for the search query at retrieval time, so it can be passed to `search_lessons_hybrid()`.

### Why
`search_lessons_hybrid()` requires both a text query and a query embedding vector. Currently `collect_relevant_lessons()` only has text tags. We need a way to embed the query efficiently during pipeline execution.

### Where
- `sysadmin/mcp_core/embeddings.py`: Reuse `embed_text()` from Stage 2A.
- `sysadmin/pipeline.py`: Modify `collect_relevant_lessons()`.

### Design Notes

**Query embedding approach**:
- For each tag/term in the search query, generate an embedding via `embed_text()`.
- Cache query embeddings within the pipeline run to avoid re-embedding the same tag across multiple stages (Orchestrator, Author, Reviewer all call `collect_relevant_lessons()`).

**Caching strategy**:
- A simple dictionary cache keyed on the query text, scoped to the pipeline run lifetime.
- Not persisted — query embeddings are ephemeral and cheap to regenerate.

**Latency budget**: Embedding a single short query should take < 100ms on local hardware. For 3-5 tags per stage, this adds ~300-500ms total per stage. This is acceptable for a pipeline that runs multi-second LLM calls.

### Acceptance Criteria
- `embed_text("shellcheck quoting bash")` returns a valid embedding vector.
- Repeated calls with the same text return cached results (no redundant Ollama calls).
- When Ollama is unavailable, embedding returns `None` and the system falls back gracefully.

---

## Step 2: Upgrade `collect_relevant_lessons()` to Hybrid Search

### What
Modify `collect_relevant_lessons()` to use `search_lessons_hybrid()` when embeddings are available, falling back to FTS5-only search when they are not.

### Where
- `sysadmin/pipeline.py`: Modify `collect_relevant_lessons()`.

### Design Notes

**Upgrade path**:
1. For each tag, generate a query embedding via `embed_text()`.
2. If the embedding is available, call `memory_store.search_lessons_hybrid(tag, embedding, top_k=search_limit)`.
3. If the embedding is `None` (Ollama unavailable or embedding module not configured), call `memory_store.search_lessons(tag, top_k=search_limit)` as before.
4. Continue to deduplicate and trim as before.

**Fallback guarantee**: The upgrade must be fully backward-compatible. If `sqlite-vec` is not installed, embeddings are NULL, or Ollama is down, the behavior is identical to the current FTS5-only path. Zero regressions.

**Import safety**: Import the embedding function conditionally. If `embeddings.py` is not importable (e.g., dependency not installed), set the embedding function to a no-op that returns `None`.

### Acceptance Criteria
- With embeddings available, `collect_relevant_lessons()` returns results that include both keyword-matched and semantically-matched lessons.
- Without embeddings, behavior is identical to the current implementation.
- No regressions in existing pipeline tests.

---

## Step 3: Tune BM25 vs Vector Weight Balance

### What
Calibrate the relative weight of BM25 keyword scores and vector cosine similarity scores in `search_lessons_hybrid()` to optimize retrieval quality.

### Why
The current `search_lessons_hybrid()` implementation uses a simple additive combination: `(fts_score + vec_score) * utility_multiplier`. This may not be optimal — BM25 scores and cosine similarity scores have different ranges and distributions. The right balance depends on the actual lesson corpus.

### Where
- `sysadmin/mcp_core/memory.py`: Modify `search_lessons_hybrid()` to accept configurable weights.

### Design Notes

**Parameterize weights**:
- Add `fts_weight: float = 0.5` and `vec_weight: float = 0.5` parameters to `search_lessons_hybrid()`.
- Combined score becomes: `(fts_weight * fts_norm + vec_weight * vec_norm) * utility_multiplier`.
- Store default weights as module-level constants for easy tuning.

**Evaluation protocol**:
1. Construct a set of 10-15 test queries with known expected lesson matches (ground truth).
2. Include queries that are:
   - **Lexically similar** to lesson text (BM25 should dominate).
   - **Semantically similar but lexically different** (vector should dominate).
   - **Mixed** (both signals contribute).
3. Run each query with different weight ratios (0.7/0.3, 0.5/0.5, 0.3/0.7).
4. Measure recall@3 (does the correct lesson appear in the top 3?) and rank position.
5. Select the weight ratio that maximizes recall@3 across the test set.

**BM25 normalization**: The current BM25 → 0..1 normalization in `search_lessons_hybrid()` divides by `max_rank`. Verify this produces a meaningful distribution. If all BM25 scores are tightly clustered, the normalization may not discriminate well.

### Acceptance Criteria
- `search_lessons_hybrid()` accepts configurable weight parameters.
- Default weights are selected based on evaluation against ground-truth query-lesson pairs.
- Evaluation results are documented with the rationale for the selected weights.
- Hybrid search recall@3 is equal to or better than FTS5-only recall@3 on the test set.

---

## Step 4: Validate Retrieval Quality End-to-End

### What
Verify that the hybrid retrieval upgrade improves lesson retrieval quality in the actual pipeline context, not just in isolated search function tests.

### Where
- Manual validation against the production database.
- Automated validation in test suite.

### Design Notes

**Manual validation**:
1. Run `collect_relevant_lessons()` with tags from a recent pipeline run.
2. Compare the returned lessons between FTS5-only and hybrid mode.
3. Identify cases where hybrid retrieval surfaces a relevant lesson that FTS5-only missed.
4. Identify any cases where hybrid retrieval introduces irrelevant noise.

**Automated validation**:
- Add test cases in `test_injection.py` or a new `test_hybrid_retrieval.py` that use pre-computed embeddings (no Ollama dependency in tests).
- Test the graceful degradation path: when embeddings are NULL, results should match FTS5-only behavior exactly.

**Regression check**: Run the full pipeline on a known task and verify prompt injection output. The injected lessons should be at least as relevant as before, with potential new semantic matches.

### Acceptance Criteria
- At least one documented case where hybrid retrieval surfaces a relevant lesson that FTS5-only misses.
- No documented cases where hybrid retrieval introduces clearly irrelevant lessons into the top-3.
- Graceful degradation test passes: NULL embeddings produce identical results to FTS5-only.
- Full test suite passes.

---

## Step 5: Graceful Degradation Verification

### What
Systematically verify that every code path degrades gracefully when embedding infrastructure is partially or fully unavailable.

### Why
The system must remain fully functional for users who don't have `sqlite-vec` installed, don't have Ollama running, or haven't backfilled embeddings. This is especially important because the pipeline is used in CI/CD-like contexts where services may not be available.

### Where
- `sysadmin/tests/`: Add degradation-specific test cases.

### Design Notes

**Degradation scenarios to test**:

| Scenario | Expected Behavior |
|----------|-------------------|
| `sqlite-vec` not importable | `search_lessons_hybrid()` falls back to `search_lessons()`. No errors. |
| Ollama not running | Query embedding returns `None`. Falls back to FTS5-only search. No errors. |
| All lesson embeddings are NULL | Vector search returns empty. Hybrid degrades to FTS5-only. |
| Some lessons have embeddings, some don't | Vector search only includes embedded lessons. FTS includes all. |
| Embedding model changed since embeddings were generated | Health check warns about staleness. Search still works with stale embeddings. |

### Acceptance Criteria
- All 5 degradation scenarios are tested and produce the expected behavior.
- No scenario raises an unhandled exception.
- Log messages clearly indicate when degradation is occurring (for operator awareness).

---

## Step 6: Commit & Documentation

### What
Commit all Stage 2B changes and update documentation.

### Where
- Feature branch.
- Update `docs/lesson_memory_update/` with tuning results and any implementation notes.

### Design Notes

**Commit strategy**: Separate commits for:
1. Query embedding pipeline and caching.
2. `collect_relevant_lessons()` hybrid upgrade.
3. Weight tuning and evaluation results.
4. Test suite additions.

**Documentation**: Record the selected weight ratio, evaluation methodology, and any observed retrieval quality improvements.

### Acceptance Criteria
- All new code committed on a feature branch.
- Full test suite passes.
- Weight tuning rationale is documented.
- Retrieval quality comparison (FTS5-only vs hybrid) is documented.
