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

## Step 1: Build Query Embedding Pipeline (Task Context & Tag Embeddings)

### What
Create a function that generates embeddings for search queries and task goal contexts at retrieval time to pass to `search_lessons_hybrid()`.

### Why
`search_lessons_hybrid()` requires both a text query and a query embedding vector. However, embedding only short 1-to-2 word taxonomy tags (e.g. `"ShellCheck"`) underutilizes dense vector capabilities. Dense embeddings excel when supplied with expressive natural language descriptions of the task goal (e.g. `"Ensure all bash scripts use set -euo pipefail, trap ERR, and assert binary existence before printing success"`).

### Where
- `sysadmin/mcp_core/embeddings.py`: Expose `embed_query()` with local caching.
- `sysadmin/pipeline.py`: Modify `collect_relevant_lessons()`.

### Design Notes

**Contextual Query Embedding Approach**:
- Support dual-query generation:
  1. **Task Goal Embedding**: Embed the prompt's primary Section 1 "Goal" / task description. This drives dense semantic retrieval across the entire knowledge base.
  2. **Tag Keywords**: Pass canonical domain tags as the FTS5 text terms for BM25 keyword matching.
- Cache query embeddings within the pipeline run (ephemeral dictionary cache) to avoid redundant Ollama calls across stages (Architect, Orchestrator, Reviewer).

**Latency budget**:
- Embedding a single query takes ~25–40ms using resident `nomic-embed-text:latest`.
- Cached for repeated stage lookups, adding < 100ms total overhead to a multi-stage pipeline run.

### Acceptance Criteria
- `embed_query("Ensure scripts fail cleanly on errors with trap line numbers")` returns a 768d vector.
- Repeated calls with identical context return cached vectors without hitting Ollama.
- When Ollama is unavailable, returns `None` and falls back gracefully to FTS5-only search.

---

## Step 2: Upgrade `collect_relevant_lessons()` to Hybrid Search

### What
Modify `collect_relevant_lessons()` to use `search_lessons_hybrid()` with prompt goal context and domain tags when embeddings are available, falling back to FTS5-only search when they are not.

### Where
- `sysadmin/pipeline.py`: Modify `collect_relevant_lessons()`.

### Design Notes

**Upgrade path**:
1. Check if embeddings are enabled and Ollama is available.
2. If available, generate the query embedding from the prompt task context (or concatenated tags if task context is unspecified).
3. Call `memory_store.search_lessons_hybrid(query_text=tag_text, query_embedding=goal_vec, top_k=search_limit)`.
4. If embeddings are unavailable (`goal_vec is None` or `sqlite-vec` missing), execute standard `memory_store.search_lessons(tag_text, top_k=search_limit)`.
5. Continue with existing deduplication and max-injection trimming.

**Fallback guarantee**:
- Zero-breaking changes: If `sqlite-vec` is not loaded, embeddings are NULL, or Ollama is offline, the function produces identical output to the legacy FTS5-only path.

### Acceptance Criteria
- With embeddings available, `collect_relevant_lessons()` retrieves both exact keyword matches and semantically relevant lessons across phrasing variations.
- Without embeddings, behavior matches legacy FTS5 output.
- Existing pipeline tests pass with 0 regressions.

---

## Step 3: Calibrate Hybrid Fusion & Rank Normalization

### What
Calibrate the score fusion formula combining BM25 keyword matching and cosine vector similarity in `search_lessons_hybrid()`.

### Why
Directly summing raw BM25 ranks and cosine similarities is problematic: BM25 ranks are unbounded negative values, and simple division by `max_rank` collapses when few items match. Cosine similarity ranges from -1 to 1 (typically 0.4 to 0.9 for semantic matches).

### Where
- `sysadmin/mcp_core/memory.py`: Refactor score fusion in `search_lessons_hybrid()`.

### Design Notes

**Fusion Algorithms Evaluated**:
1. **Reciprocal Rank Fusion (RRF)**:
   $$\text{Score}(d) = \frac{w_{\text{fts}}}{k + \text{rank}_{\text{fts}}(d)} + \frac{w_{\text{vec}}}{k + \text{rank}_{\text{vec}}(d)}$$
   (with $k=60$ standard smoothing constant). RRF is resilient to outlier score distributions and does not require tricky score normalization.
2. **Min-Max Normalized Linear Combination**:
   $$\text{Score}(d) = \left(w_{\text{fts}} \cdot \text{Norm}(\text{BM25}) + w_{\text{vec}} \cdot \text{CosineSim}\right) \times \text{UtilityMultiplier}$$
   With calibrated default weights ($w_{\text{fts}} = 0.45, w_{\text{vec}} = 0.55$).

**Evaluation protocol**:
- Test against ground-truth pairs:
  - Exact tag matches (e.g. tag `shellcheck` matching SC quoting rules).
  - Vocabulary-shifted queries (e.g. `"proactive risk prevention"` matching defensive scripting rules without the word "shellcheck").
- Verify that utility suppression (`(prevented + 1) / (retrieved + 2)`) applies uniformly to the combined score.

### Acceptance Criteria
- `search_lessons_hybrid()` accepts configurable fusion weights.
- Score fusion handles edge cases cleanly (single-match BM25, negative cosine, ties).
- Hybrid search recall@3 is superior to FTS5-only search on test queries.

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
