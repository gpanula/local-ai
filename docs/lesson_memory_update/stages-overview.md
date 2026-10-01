# Lesson Memory System Update — Staged Roadmap

> **Date**: 2026-09-30
> **Purpose**: Outlines the phased approach to upgrading the lesson learning & memory system's deduplication, embedding, retrieval, and scaling capabilities.

---

## Overview

The lesson memory system upgrade is organized into four stages with strict dependency ordering. Each stage produces a testable, independently valuable deliverable that the next stage builds upon.

```mermaid
graph LR
    S1["Stage 1\nLexical Dedup Lifecycle"] --> S2A["Stage 2A\nEmbedding Infrastructure"]
    S2A --> S2B["Stage 2B\nHybrid Retrieval"]
    S2B --> S3["Stage 3\nSemantic Dedup & Scaling"]

    style S1 fill:#2d6a4f,stroke:#1b4332,color:#fff
    style S2A fill:#1d3557,stroke:#0d1b2a,color:#fff
    style S2B fill:#457b9d,stroke:#1d3557,color:#fff
    style S3 fill:#6a040f,stroke:#370617,color:#fff
```

---

## Source Documents

| Document | Purpose |
|----------|---------|
| [fix-lesson-duplication-detection.md](fix-lesson-duplication-detection.md) | Root cause analysis, implemented downstream fix, proposed upstream solution |
| [review-lesson-duplication-detection.md](review-lesson-duplication-detection.md) | Architectural review: 8 identified problems with solutions |
| [analysis-lesson-duplication-detection.md](analysis-lesson-duplication-detection.md) | Expert review: what was right, wrong, and missed |

---

## Stage 1: Lexical Dedup Lifecycle

**Goal**: Eliminate duplicate lessons at every lifecycle transition using the existing lexical similarity engine. No new dependencies.

**Scope**:
- Fix `are_rules_similar()` normalization inconsistency
- Unify the similarity threshold constant
- Implement ingestion guard in `stage_pending_lesson()` (active + pending dedup)
- Implement promotion guard in `promote_pending_lesson()` (active dedup + `is_new` return contract)
- Add rule-text similarity clustering for compaction (`cluster_lessons_by_similarity()`)
- Fix `lessons.md` desync on duplicate promotion
- Invalidate stale embeddings during active lesson compaction
- Add TOCTOU concurrency guard (SQLite `BEGIN IMMEDIATE`)
- Add lesson decay / sunset flagging
- Add full lifecycle integration test
- Execute one-time compaction cleanup via `localai-compact --auto`
- Update test fixtures with realistic phrasing variants

**Key Metrics**: Pending lessons: 17 → ≤6. Active lessons: 66 → ~28 distinct. Zero duplicate lessons in prompt injection output.

**Implementation Plan**: [stage-1-implementation-plan.md](stage-1-implementation-plan.md)

---

## Stage 2A: Embedding Infrastructure

**Goal**: Build the embedding generation and lifecycle pipeline so every lesson has a dense vector representation stored in SQLite via `sqlite-vec`.

**Scope**:
- Benchmark and select a local Ollama embedding model
- Build the embedding generation function (`embed_lesson_rule()`)
- Add lifecycle hooks: embed on insert, embed on update, invalidate + re-embed on compaction
- Backfill embeddings for all existing active lessons
- Add embedding health monitoring (coverage, staleness detection)
- Validate `sqlite-vec` extension loading and vector storage

**Key Metrics**: 100% embedding coverage on active lessons. All vector search functions (`search_lessons_vector()`, `search_lessons_hybrid()`) return results.

**Implementation Plan**: [stage-2a-implementation-plan.md](stage-2a-implementation-plan.md)

---

## Stage 2B: Hybrid Retrieval Upgrade

**Goal**: Wire hybrid search (BM25 + vector similarity) into the lesson retrieval pipeline as the primary search path, improving retrieval quality for semantically similar but lexically different queries.

**Scope**:
- Upgrade `collect_relevant_lessons()` to use `search_lessons_hybrid()` when embeddings are available
- Build a query embedding pipeline (embed the search query at retrieval time)
- Tune BM25 vs vector weight balance
- Validate retrieval quality against known query → lesson pairs
- Ensure graceful degradation when embeddings are unavailable

**Key Metrics**: Hybrid search retrieves relevant lessons that FTS5-only search misses. Zero regression on existing retrieval quality.

**Implementation Plan**: [stage-2b-implementation-plan.md](stage-2b-implementation-plan.md)

---

## Stage 3: Semantic Dedup & Scaling

**Goal**: Replace O(n²) pairwise comparisons with embedding-based approximate nearest neighbor (ANN) pre-filtering, and add semantic duplicate detection that catches vocabulary-shifted duplicates.

**Scope**:
- Build `are_rules_similar_v2()` combining lexical (Jaccard) and semantic (cosine) similarity signals
- Replace pairwise scans in ingestion and compaction with ANN candidate pre-filtering via `sqlite-vec`
- Add cross-category semantic deduplication
- Benchmark scaling: verify sub-linear performance on 500+ lesson corpus
- Add MinHash/LSH fallback for environments without `sqlite-vec`

**Key Metrics**: Ingestion guard runs in O(1) amortized (ANN lookup + constant comparisons). Compaction scales sub-linearly. Semantic duplicates (different vocabulary, same meaning) are detected.

**Implementation Plan**: [stage-3-implementation-plan.md](stage-3-implementation-plan.md)

---

## Dependency Chain & Risk Assessment

| Stage | Depends On | Primary Risk | Mitigation |
|-------|-----------|-------------|------------|
| **1** | Nothing | Test fixture regressions from dedup behavior changes | `deduplicate: bool = True` parameter; update fixtures first |
| **2A** | Stage 1 | Embedding model quality/performance on short lesson text | Include benchmarking step before committing to a model |
| **2B** | Stage 2A | Weight tuning: BM25 vs vector balance may need iteration | Build with configurable weights; test with real queries |
| **3** | Stage 2B | ANN accuracy on small corpus (sqlite-vec may not shine at <100 items) | Keep lexical fallback; ANN is a pre-filter, not the sole signal |
