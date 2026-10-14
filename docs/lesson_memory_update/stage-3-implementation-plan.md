# Stage 3 Implementation Plan: Semantic Dedup & Scaling

> **Parent**: [stages-overview.md](stages-overview.md)
> **Prerequisites**: [Stage 2B](stage-2b-implementation-plan.md) completed (hybrid retrieval working, all lessons embedded, vector search validated)
> **Estimated Scope**: ~7 steps across 4 source files + 3 test files

---

## Objective

Replace O(n²) pairwise comparisons with embedding-based approximate nearest neighbor (ANN) pre-filtering, and add semantic duplicate detection that catches vocabulary-shifted duplicates that lexical similarity misses. This stage transforms the deduplication engine from a lexical-only system to a hybrid lexical+semantic system that scales sub-linearly.

---

## Current State (After Stage 2B)

- Every active lesson has a dense vector embedding.
- `are_rules_similar()` uses Jaccard + SequenceMatcher (lexical only).
- Ingestion guard in `stage_pending_lesson()` scans all active + pending lessons: O(n²).
- Compaction clustering uses pairwise comparisons: O(n²).
- Semantic duplicates (same meaning, different words) are not detected.
- sqlite-vec ANN search is available but only used for retrieval, not deduplication.

---

## Step 1: Build `are_rules_similar_v2()` — Tiered Disjunctive Similarity

### What
Create an upgraded similarity function combining lexical signals (Jaccard, SequenceMatcher) with semantic signals (cosine similarity on embeddings) using a **tiered disjunctive decision gate** rather than a strict linear weighted average.

### Why
In Stage 1 testing, `lesson-20260918-05` and `lesson-20260929-01` were semantically identical, but because one rule embedded raw bash syntax (`trap 'echo "..."' ERR`), the token Jaccard similarity dropped to `0.188`.
Under a naive weighted formula like `0.4 * lexical + 0.6 * cosine`, a high cosine match of `0.90` yields `0.4*0.188 + 0.6*0.90 = 0.615 < 0.65`, failing to merge.

A tiered decision gate ensures that high semantic equivalence triggers deduplication regardless of low token overlap caused by code syntax or vocabulary shifts.

### Where
- `sysadmin/mcp_core/injection.py`: Add `are_rules_similar_v2()` alongside the existing function.

### Design Notes

**Decision Gate Logic**:
```python
def are_rules_similar_v2(
    rule1: str,
    rule2: str,
    emb1: Optional[list[float]] = None,
    emb2: Optional[list[float]] = None,
    lexical_threshold: float = SIMILARITY_THRESHOLD, # 0.75
    semantic_threshold: float = 0.82,
    hybrid_lexical: float = 0.40,
    hybrid_semantic: float = 0.70,
) -> tuple[bool, str]:
    """Check if two rules are similar.
    
    Returns (is_similar, match_reason) where match_reason is one of:
      'lexical', 'semantic', 'hybrid', or 'none'.
    """
    # 1. Lexical evaluation
    lexical_score = compute_lexical_similarity(rule1, rule2)
    if lexical_score >= lexical_threshold:
        return True, "lexical"

    # 2. Semantic evaluation (if embeddings are provided)
    if emb1 is not None and emb2 is not None:
        cos_sim = _cosine_similarity(emb1, emb2)
        # Strong semantic equivalence overrides vocabulary / syntax differences
        if cos_sim >= semantic_threshold:
            return True, "semantic"
        # Balanced hybrid match
        if lexical_score >= hybrid_lexical and cos_sim >= hybrid_semantic:
            return True, "hybrid"

    return False, "none"
```

**Short-text guard**:
- For short rules (< 25 characters), raise `semantic_threshold` to `0.88` to avoid false positives on terse general statements.

**Option A (Pre-computed Embeddings)**:
- Accept embeddings as optional parameters. When callers (e.g. `MemoryStore`) already have cached vectors, comparison is instant. When embeddings are `None`, falls back cleanly to lexical-only comparison.

### Acceptance Criteria
- `are_rules_similar_v2()` returns `True, "semantic"` for code-shifted pairs like `lesson-20260918-05` and `lesson-20260929-01`.
- `are_rules_similar_v2()` returns `False, "none"` for distinct rules in the same category.
- When embeddings are `None`, behavior matches `are_rules_similar()` (100% backward compatible).
- Match reason (`lexical`, `semantic`, `hybrid`) is returned for telemetry and TUI display.

---

## Step 2: Vector Candidate Pre-Filter for Ingestion Guard

### What
Replace the O(n) full-scan similarity check in `stage_pending_lesson()` with a vector distance candidate pre-filter, followed by `are_rules_similar_v2()` evaluation on candidates.

### Where
- `sysadmin/mcp_core/memory.py`: Modify dedup logic in `stage_pending_lesson()`.

### Design Notes

**Candidate Selection & Indexing Strategy**:
- For corpora under ~2,000 lessons, SQLite's scalar function `vec_distance_cosine()` over an indexed `embeddings IS NOT NULL` table executes in **< 4 milliseconds**.
- Query candidate lessons:
  ```sql
  SELECT id, rule, embeddings, vec_distance_cosine(embeddings, ?) AS vec_dist
  FROM lessons
  WHERE embeddings IS NOT NULL
  ORDER BY vec_dist ASC
  LIMIT 15;
  ```
- Run `are_rules_similar_v2()` only on the top-15 candidates.
- If an active rule matches (`is_similar=True`), bump reinforcement/ineffective counts instead of inserting a duplicate.
- *Scaling note*: For future multi-user deployments exceeding 5,000 lessons, a `vec0` virtual table index can be migrated without modifying the caller interface.

**Pending Queue Embeddings**:
- Embed pending lessons at staging time so the pending review queue also benefits from semantic candidate pre-filtering.

### Acceptance Criteria
- Ingestion pre-filter catches semantic duplicates at staging time.
- Operates in < 15ms per ingestion event.
- Gracefully falls back to lexical scan when Ollama or `sqlite-vec` is offline.

---

## Step 3: Compaction Clustering & TUI Integration

### What
1. Upgrade `cluster_lessons_by_similarity()` to use vector candidate pre-filtering.
2. Surface similarity origin badges (`[SEMANTIC]`, `[LEXICAL]`, `[HYBRID]`) and cosine similarity in the Consolidation TUI (`compact_app.py`).

### Where
- `sysadmin/mcp_core/audit.py`: Update `cluster_lessons_by_similarity()`.
- `sysadmin/lessons_tui/widgets/cluster_list.py` & `cluster_detail.py`: Display match origin and similarity scores.

### Design Notes

**Clustering Algorithm**:
1. For each lesson with an embedding, query the top-10 nearest neighbors.
2. Confirm pairwise similarity via `are_rules_similar_v2()`.
3. Track cluster metadata: match type (`semantic`, `lexical`, `hybrid`) and maximum cosine similarity.
4. Build union-find connected components.

**Consolidation TUI Display**:
- In `ClusterListView`: Tag clusters with badges:
  - `[SEMANTIC 0.88]` (semantic match with code/vocabulary shift)
  - `[LEXICAL 0.81]` (text overlap)
  - `[HYBRID 0.74]` (both signals contributed)
- In `ClusterDetailView`: Display individual pairwise similarity scores and allow the operator to inspect exactly why the cluster was proposed.

### Acceptance Criteria
- Compaction clustering correctly groups `lesson-20260918-05` and `lesson-20260929-01` into a semantic cluster.
- TUI displays match type and similarity metric for each cluster.
- Unembedded lessons are clustered via lexical fallback pass.

---

## Step 4: Cross-Category Semantic Deduplication

### What
Ensure that semantic duplicates across different categories are detected and resolved during compaction and ingestion.

### Why
Vocabulary-shifted rules across distinct categories (e.g. `ShellCheck` vs `Defensive Bash Scripting`) share semantic intent but no exact category keyword. Embeddings are category-agnostic and naturally bridge cross-domain duplicates.

### Where
- `sysadmin/mcp_core/memory.py`: Ingestion guard vector query.
- `sysadmin/mcp_core/audit.py`: Compaction clustering vector query.

### Design Notes

**Category Reconciliation**:
- When two lessons from different categories merge:
  1. Combine keyword sets.
  2. Re-normalize category using `normalize_category(combined_keywords)`.
  3. Prefer canonical categories over specialized ones.
- Log cross-category merges explicitly in wiki `log.md` and TUI status bar.

### Acceptance Criteria
- Cross-category duplicates are grouped into unified clusters.
- Category reconciliation selects the most accurate canonical category.
- Cross-category merges are highlighted in TUI and logs.

---

## Step 5: Scaling Benchmark

### What
Benchmark the system at various corpus sizes to validate sub-linear scaling and establish performance baselines.

### Where
- Create a benchmark script (can be a test file or standalone script).

### Design Notes

**Benchmark protocol**:
1. Generate synthetic lesson corpora at sizes: 50, 100, 250, 500, 1000, 2000.
2. Use realistic lesson text (generated from templates with category-appropriate vocabulary).
3. Embed all synthetic lessons.
4. Measure:
   - **Ingestion time**: Time to call `stage_pending_lesson()` with a duplicate rule.
   - **Compaction time**: Time to run `cluster_lessons_by_similarity()` on the full corpus.
   - **Retrieval time**: Time to call `collect_relevant_lessons()` with 3 tags.
5. Compare ANN-based (Stage 3) vs full-scan (Stage 1) for ingestion and compaction.
6. Plot time vs corpus size to verify sub-linear scaling.

**Performance targets**:
- Ingestion: < 200ms per call at 2000 lessons (ANN approach).
- Compaction: < 5 seconds for full corpus at 2000 lessons.
- Retrieval: < 500ms per call at 2000 lessons (hybrid search).

### Acceptance Criteria
- Benchmark results show sub-linear scaling for ingestion and compaction with ANN.
- Performance targets are met at 2000 lessons.
- Results are documented with charts/tables.

---

## Step 6: MinHash/LSH Fallback (Optional)

### What
Implement a MinHash-based Locality-Sensitive Hashing (LSH) index as a fallback for environments where `sqlite-vec` is not available, providing O(n) amortized dedup without embedding dependencies.

### Why
Some environments may not have `sqlite-vec` or Ollama available. MinHash/LSH operates on token sets (no embeddings needed) and provides approximate nearest-neighbor lookup for Jaccard similarity.

### Where
- `sysadmin/mcp_core/lsh.py` (new file, optional module).

### Design Notes

**Implementation approach**:
- MinHash signatures: For each lesson rule, compute a MinHash signature (128 hash functions is typical) over the token set.
- LSH bands: Divide the signature into bands (e.g., 16 bands of 8 hashes). Two rules are candidate duplicates if any band matches exactly.
- This gives approximate Jaccard similarity > 0.5 with high probability.

**Integration**: Use as a pre-filter in `stage_pending_lesson()` and `cluster_lessons_by_similarity()` when `sqlite-vec` is unavailable and the corpus exceeds a size threshold (e.g., 200 lessons). Below the threshold, the O(n²) approach is fast enough.

**Scope note**: This step is explicitly optional. It's a future-proofing measure for large-scale deployments without sqlite-vec. If the team decides sqlite-vec will always be available, this can be skipped.

### Acceptance Criteria
- MinHash/LSH pre-filter produces the same dedup results as full-scan on the current corpus.
- At 1000+ lessons without sqlite-vec, MinHash ingestion is faster than full-scan.
- The module is optional and does not affect systems with sqlite-vec.

---

## Step 7: Commit, Documentation & Stage Completion

### What
Commit all Stage 3 changes, update documentation, and validate the complete system end-to-end.

### Where
- Feature branch.
- Update `docs/lesson_memory_update/` with benchmark results and architecture notes.

### Design Notes

**Final integration test**: Run the full lifecycle integration test (from Stage 1) with the Stage 3 code to verify no regressions. Additionally:
- Verify that semantic duplicates are caught at ingestion.
- Verify that compaction identifies cross-category semantic clusters.
- Verify that prompt injection output contains no semantic duplicates.

**Architecture documentation**: Update the stages overview to mark Stage 3 as complete. Write a brief "Lesson Memory System Architecture" document describing the final state of the system: lexical + semantic dedup, ANN-based scaling, hybrid retrieval, lifecycle guards, and decay management.

**Commit strategy**: Separate commits for:
1. `are_rules_similar_v2()` hybrid similarity function.
2. ANN pre-filter for ingestion.
3. ANN-based compaction clustering.
4. Cross-category dedup handling.
5. Benchmark script and results.
6. MinHash/LSH fallback (if implemented).

### Acceptance Criteria
- Full test suite passes.
- Lifecycle integration test passes with semantic dedup.
- Benchmark results show sub-linear scaling.
- Architecture documentation is complete.
- All changes committed with gitmoji conventional commits.
