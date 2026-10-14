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

## Step 1: Build `are_rules_similar_v2()` — Hybrid Similarity

### What
Create an upgraded similarity function that combines lexical signals (Jaccard, SequenceMatcher) with semantic signals (cosine similarity on embeddings) for more accurate near-duplicate detection.

### Where
- `sysadmin/mcp_core/injection.py`: Add `are_rules_similar_v2()` alongside the existing function.

### Design Notes

**Hybrid scoring approach**:
The function should combine three signals:
1. **Token Jaccard similarity** — catches exact/near-exact word overlap.
2. **Character SequenceMatcher ratio** — catches character-level rearrangements and minor edits.
3. **Cosine similarity on embeddings** — catches semantic equivalence with different vocabulary.

**Combining strategy**: Weighted combination rather than hard thresholds on each signal. This avoids the brittleness of requiring all three to pass independently.

Proposed formula:
```
combined_score = (
    lexical_weight * max(jaccard, seq_ratio)
    + semantic_weight * cosine_sim
)
is_similar = combined_score >= combined_threshold
```

**Weight selection**: Start with `lexical_weight=0.4, semantic_weight=0.6, combined_threshold=0.65`. The semantic signal should dominate because it catches the cases lexical similarity misses (which is the entire point of Stage 3). The lexical signal provides a safety net for short texts where embeddings may be noisy.

**Short-text guard**: Preserve the existing guard for very short texts (< 25 chars). On short text, embeddings are less reliable, so increase `lexical_weight` and decrease `semantic_weight` dynamically.

**Embedding generation**: The function needs embeddings for both rules. Two options:
- **Option A (preferred)**: Accept pre-computed embeddings as optional parameters. Callers that already have embeddings (e.g., from the database) pass them in. Callers without embeddings get lexical-only comparison.
- **Option B**: Generate embeddings on the fly via `embed_text()`. This introduces Ollama latency into every comparison.

Option A is preferred because it keeps the function fast and deterministic for callers that have cached embeddings, while still working (lexical-only) when embeddings are unavailable.

**Backward compatibility**: The existing `are_rules_similar()` must remain available and unchanged for Stage 1 code paths that don't have embeddings. `are_rules_similar_v2()` is a superset that falls back to lexical-only behavior when embeddings are `None`.

### Acceptance Criteria
- `are_rules_similar_v2("Always quote variables", "Use double-quotes around parameter expansions", emb1, emb2)` returns `True` (semantic match that v1 misses).
- `are_rules_similar_v2("Always quote variables", "Never use eval in production", emb1, emb2)` returns `False` (correctly distinguishes unrelated rules).
- When embeddings are `None`, behavior is equivalent to `are_rules_similar()`.
- Short texts (< 25 chars) are handled with increased lexical weight.

---

## Step 2: ANN Pre-Filter for Ingestion Guard

### What
Replace the O(n) full-scan similarity check in `stage_pending_lesson()` with an ANN pre-filter that uses `sqlite-vec` to find candidate near-duplicates, then runs `are_rules_similar_v2()` only on those candidates.

### Why
Currently `stage_pending_lesson()` (after Stage 1) compares the incoming rule against every active and pending lesson. At 500+ lessons, this becomes a performance bottleneck. ANN search returns the top-K most similar vectors in approximately O(log n) time, reducing the comparison set dramatically.

### Where
- `sysadmin/mcp_core/memory.py`: Modify the dedup logic in `stage_pending_lesson()`.

### Design Notes

**ANN query approach**:
1. Generate an embedding for the incoming `proposed_rule` via `embed_text()`.
2. Query sqlite-vec for the top-K closest lessons by cosine distance: `SELECT id, rule, embeddings, vec_distance_cosine(embeddings, ?) AS dist FROM lessons WHERE embeddings IS NOT NULL ORDER BY dist ASC LIMIT ?`
3. Use a generous K (e.g., 10-20) to avoid missing true duplicates.
4. Run `are_rules_similar_v2()` on each candidate with the pre-fetched embeddings.
5. If any candidate matches, handle as before (active match → bump `ineffective_count`; pending match → merge).

**Pending lessons**: Pending lessons may not have embeddings (they're not embedded until promotion in the current design). For pending dedup, either:
- Embed pending lessons at staging time (adds an Ollama call per staging).
- Fall back to lexical-only scan for pending lessons.

Recommended: Embed pending lessons at staging time. The cost is one embedding call per staging event, which is negligible compared to the LLM calls in the pipeline. This enables ANN-based pending dedup as well.

**Fallback**: If the embedding generation fails or `sqlite-vec` is unavailable, fall back to the Stage 1 full-scan behavior. The ANN pre-filter is a performance optimization, not a correctness requirement.

### Acceptance Criteria
- Ingestion with ANN pre-filter produces the same dedup results as the full-scan approach on the current corpus (correctness validation).
- At 500+ lessons (synthetic test), ANN pre-filter ingestion is measurably faster than full-scan.
- When `sqlite-vec` is unavailable, behavior falls back to Stage 1 full-scan.
- Pending lessons receive embeddings at staging time.

---

## Step 3: ANN-Based Compaction Clustering

### What
Replace the O(n²) pairwise comparison in `cluster_lessons_by_similarity()` with ANN-based candidate generation, reducing compaction time on large lesson sets.

### Where
- `sysadmin/mcp_core/audit.py`: Modify `cluster_lessons_by_similarity()`.

### Design Notes

**ANN clustering approach**:
1. For each lesson with an embedding, query sqlite-vec for its K nearest neighbors (K=10).
2. For each neighbor pair, run `are_rules_similar_v2()` to confirm similarity.
3. Build the union-find connected components from confirmed similar pairs.
4. This reduces comparisons from O(n²) to O(n·K) where K is a small constant.

**Lessons without embeddings**: Include them in a lexical-only fallback pass. Compare each unembedded lesson against all other lessons using `are_rules_similar()` (v1). This subset is expected to be small (newly staged lessons before embedding backfill).

**Correctness validation**: Before deploying ANN clustering as the default, run both the old O(n²) approach and the new ANN approach on the same corpus and verify they produce identical clusters. Any difference indicates the K value is too small (true duplicates not in top-K neighbors).

### Acceptance Criteria
- ANN clustering produces the same clusters as O(n²) clustering on the current corpus.
- At 500+ lessons, ANN clustering is measurably faster.
- Lessons without embeddings are handled via lexical fallback.
- K value is documented and justified.

---

## Step 4: Cross-Category Semantic Deduplication

### What
Ensure that semantic duplicates across different categories are detected and handled, both at ingestion time and during compaction.

### Why
After Stage 1, category-agnostic lexical scans catch cross-category duplicates that share words. But vocabulary-shifted duplicates across categories (e.g., a `ShellCheck` lesson about quoting vs a `Defensive Bash Scripting` lesson about quoting with different phrasing) are only catchable with semantic similarity.

### Where
- Already handled by the ANN pre-filter in Steps 2 and 3 (embeddings are category-agnostic).
- `sysadmin/mcp_core/memory.py`: Verify ingestion guard ANN query does not filter by category.
- `sysadmin/mcp_core/audit.py`: Verify compaction ANN query does not filter by category.

### Design Notes

**Category merging on cross-category dedup**:
When two lessons from different categories are identified as semantic duplicates:
- During compaction: Keep the category of the lesson with the most specific/canonical category. Re-evaluate via `normalize_category()` on the merged keyword set.
- During ingestion: If the incoming lesson matches an active lesson in a different category, the existing active lesson's category is preserved. The incoming lesson's keywords are merged.

**Documentation**: Cross-category dedup may surface unexpected merges (e.g., "ShellCheck" lesson merged into "Defensive Bash Scripting"). Log these events for operator review. Consider adding a `--verbose` flag to `localai-compact` that shows cross-category merges explicitly.

### Acceptance Criteria
- Two semantically identical lessons in different categories are detected as duplicates.
- Category re-evaluation produces the most specific canonical category.
- Cross-category merges are logged for visibility.
- No unrelated lessons across categories are falsely merged.

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
