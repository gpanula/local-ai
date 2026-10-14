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

## Stage 1: Lexical Dedup Lifecycle (COMPLETED ✅)

**Status**: Completed in PR #10 and merged into `main` in PR #7.

**Deliverables**:
- Normalized `are_rules_similar()` with unified `0.75` Jaccard threshold
- Ingestion and promotion guards with reinforcement tracking
- Rule-text similarity clustering for compaction (`cluster_lessons_by_similarity()`)
- SQLite concurrency guard (`BEGIN IMMEDIATE`)
- Lesson decay and sunset candidate flagging (`flag_low_utility`) with operational pipeline padding
- `--retire-sunsets` flag in CLI (`localai-compact-lessons`, `localai-compact-active`)
- Textual Compaction TUI (`compact_app.py`) with 3-way tab cycling (`[Pending Queue]`, `[Active Lessons]`, `[Sunset Candidates]`)
- Full test suite passing (393/393)

**Implementation Plan**: [stage-1-implementation-plan.md](stage-1-implementation-plan.md)

---

## Stage 2A: Embedding Infrastructure

**Goal**: Build the embedding generation and lifecycle pipeline so every active lesson has a dense vector representation stored in SQLite via `sqlite-vec`.

**Scope**:
- Verify and adopt the resident local embedding model (`nomic-embed-text:latest`, 768 dimensions)
- Add native `ollama_embed` MCP tool to `sysadmin/mcp_ollama/server.py` adhering to Rule 7
- Build embedding generation module (`sysadmin/mcp_core/embeddings.py`)
- Add lifecycle hooks: embed on insert, embed on update, invalidate on compaction
- Backfill embeddings for all existing active lessons (`refresh_all_embeddings()` / CLI)
- Surface embedding status (`[EMBEDDED]` / `[NO-VEC]`) in Compaction TUI (`compact_app.py`)
- Validate `sqlite-vec` vector and hybrid search functions

**Key Metrics**: 100% embedding coverage on active lessons. All vector search functions (`search_lessons_vector()`, `search_lessons_hybrid()`) return verified results.

**Implementation Plan**: [stage-2a-implementation-plan.md](stage-2a-implementation-plan.md)

---

## Stage 2B: Hybrid Retrieval Upgrade

**Goal**: Wire hybrid search (BM25 + vector similarity) into the lesson retrieval pipeline as the primary search path, using prompt goal context for dense vector matching.

**Scope**:
- Upgrade `collect_relevant_lessons()` in `pipeline.py` to embed the **task prompt/goal context** (rather than isolated 2-word tags) for vector retrieval
- Calibrate hybrid fusion using Reciprocal Rank Fusion (RRF) or normalized min-max weighting
- Build query embedding pipeline with ephemeral pipeline-run caching
- Validate retrieval quality against known query → lesson pairs
- Ensure zero-regression graceful degradation when embeddings or Ollama are unavailable

**Key Metrics**: Hybrid search retrieves relevant lessons that FTS5-only search misses. Zero regression on existing retrieval quality.

**Implementation Plan**: [stage-2b-implementation-plan.md](stage-2b-implementation-plan.md)

---

## Stage 3: Semantic Dedup & Scaling

**Goal**: Introduce semantic duplicate detection that catches vocabulary-shifted and code-shifted duplicates, combined with vector pre-filtering and TUI clustering badges.

**Scope**:
- Build `are_rules_similar_v2()` using a **tiered disjunctive decision gate** (`lexical_pass OR semantic_pass OR hybrid_pass`) to solve vocabulary/code shift gaps
- Use scalar `vec_distance_cosine()` candidate pre-filtering for sub-second clustering (under 2,000 lessons), documenting `vec0` virtual table indexing for scale
- Surface similarity origin badges (`[SEMANTIC]`, `[LEXICAL]`, `[HYBRID]`) and cosine similarity metrics in Compaction TUI (`compact_app.py`)
- Add cross-category semantic deduplication
- Benchmark scaling performance up to 1,000+ lesson corpus
- Optional MinHash/LSH fallback for non-vector environments

**Key Metrics**: Semantic duplicates (different vocabulary/code snippets, same meaning) are caught. Compaction triage clearly distinguishes semantic vs lexical clusters.

**Implementation Plan**: [stage-3-implementation-plan.md](stage-3-implementation-plan.md)

---

## Dependency Chain & Risk Assessment

| Stage | Depends On | Primary Risk | Mitigation |
|-------|-----------|-------------|------------|
| **1** | Nothing | Test fixture regressions from dedup behavior changes | `deduplicate: bool = True` parameter; update fixtures first |
| **2A** | Stage 1 | Embedding model quality/performance on short lesson text | Include benchmarking step before committing to a model |
| **2B** | Stage 2A | Weight tuning: BM25 vs vector balance may need iteration | Build with configurable weights; test with real queries |
| **3** | Stage 2B | ANN accuracy on small corpus (sqlite-vec may not shine at <100 items) | Keep lexical fallback; ANN is a pre-filter, not the sole signal |
