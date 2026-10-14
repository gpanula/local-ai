# Expert Review: Lesson Duplication Detection Architecture

> **Date**: 2026-09-30
> **Reviewer Perspective**: AI/ML engineering — similarity systems, retrieval pipelines, embedding search, data lifecycle.
> **Source Documents**: [fix-lesson-duplication-detection.md](fix-lesson-duplication-detection.md), [review-lesson-duplication-detection.md](review-lesson-duplication-detection.md)

---

## 1. Overview

This document provides an independent expert review of the two lesson duplication detection documents: the original root cause analysis & fix ([fix doc](fix-lesson-duplication-detection.md)) and the subsequent architectural review ([review doc](review-lesson-duplication-detection.md)). The goal is to identify what was done well, what was incorrect, and what was missed — with concrete solutions for each shortcoming.

---

## 2. What They Got Right ✅

### 2.1 Root Cause Analysis (Fix Doc, §2)

The four-gap analysis (blind ingestion → metadata-only clustering → blind promotion → exact-equality retrieval) is accurate, well-evidenced, and correctly sequenced from upstream to downstream. The mermaid flow diagram is a clear, traceable system map.

### 2.2 Implemented Dual-Signal Similarity (Fix Doc, §3)

The `are_rules_similar()` function in `sysadmin/mcp_core/injection.py` is a well-designed approach:
- **Jaccard + SequenceMatcher hybrid** covers both token-level and character-level similarity — a solid choice for short-text deduplication where embeddings are overkill.
- The **short-string guard** (ratio ≥ 0.92 *and* min length > 25) correctly prevents false positives on terse labels like `"Rule A"` vs `"Rule C"`. This is a common pitfall many implementations miss.
- **Headroom querying** (`max(top_k * 3, 10)`) in `collect_relevant_lessons()` is the correct retrieval engineering pattern: over-fetch, deduplicate, then trim.

### 2.3 Edge Case Identification (Review Doc, §2)

The review doc catches genuinely critical issues:

| Problem | Verdict |
|---------|---------|
| **P1: `lessons.md` desync** on promotion | 🎯 Critical. The `append_lesson_to_markdown` + reinforcement path is a real bug. The `(lesson_id, is_new)` tuple return is the correct fix. |
| **P2: Active match semantics** in staging | 🎯 Correct. Incrementing `ineffective_count` (not `retrieval_count`) when a pipeline fails on an already-known lesson is the right telemetry semantic. |
| **P3: `cluster_lessons` purpose conflict** | 🎯 Accurate. Wiki/taxonomy clustering and deduplication compaction are fundamentally different operations. Separating them is correct. |
| **P4: Test fixture regressions** | 🎯 Practical. The `deduplicate: bool = True` parameter for testing is a pragmatic solution. |
| **P5: Stale embeddings** | 🎯 Real bug. Updating rule text without invalidating the embedding vector is a classic ML pipeline cache-coherency failure. |
| **P6: Taxonomy re-evaluation** | ✅ Good catch. Merged keyword sets can resolve previously ambiguous categories. |
| **P7: One-off script redundancy** | 🎯 Good engineering judgment. Reusing `localai-compact --auto` instead of throwaway scripts follows DRY. |
| **P8: Threshold drift** | 🎯 Correct. The `0.75` vs `0.78` divergence is already present in the codebase. |

### 2.4 End-to-End Lifecycle Diagram (Review Doc, §3)

The three-phase mermaid diagram (Staging → Compaction → Promotion) correctly captures the guard/gate pattern at every lifecycle transition. This is the clearest artifact across both documents.

---

## 3. What They Got Wrong ❌

### 3.1 Normalization Inconsistency in the Similarity Function

`are_rules_similar()` operates on **raw rule text**, but `deduplicate_lessons()` passes **normalized text** (via `normalize_lesson_rule()`, which strips all non-alphanumeric characters and lowercases). The function doesn't know whether it's receiving raw or pre-normalized input.

The proposed upstream uses (staging, compaction) in both docs casually say "normalize incoming proposed_rule" then call `are_rules_similar()`. This creates **inconsistent normalization**: some callsites pre-normalize, others don't.

**Fix**: `are_rules_similar()` must internally normalize both inputs at the top of the function, making it safe to call with either raw or pre-normalized text. This is idempotent — normalizing already-normalized text produces the same result.

### 3.2 Threshold Mismatch Is Deeper Than Stated

The review doc (P8) notes the `0.75` vs `0.78` divergence but doesn't flag the deeper issue: `deduplicate_lessons()` at threshold `0.78` is **stricter** than `are_rules_similar()`'s default `0.75`. This means:

- The ingestion guard (proposed at `0.75`) would merge items that `deduplicate_lessons()` (at `0.78`) would keep separate at retrieval time.
- A lesson could be silently merged at staging, then a nearly-identical surviving lesson could still appear as "distinct" during prompt injection.

The fix should not just centralize the constant — it should **pick one threshold** and justify it with test cases, or explicitly document why different lifecycle stages use different thresholds.

### 3.3 Jaccard Similarity Is Not Semantically Aware

Both documents treat `are_rules_similar()` as a sufficient deduplication oracle. But Jaccard + SequenceMatcher is a **lexical** similarity measure. It will miss semantic duplicates with different vocabulary:

- *"Always quote variables in shell scripts"* vs *"Use double-quotes around parameter expansions in bash"* → **Jaccard ≈ 0.10**, **SequenceMatcher ≈ 0.25**. These are semantically identical but will **not** be detected as duplicates.

Neither document acknowledges this limitation. For the current dataset (17 pending lessons with obvious lexical overlap), the approach works fine. But as the lesson corpus grows and LLM-generated phrasings diversify, this will degrade.

---

## 4. What Was Missed 🕳️

### 4.1 O(n²) Scaling in Deduplication and Clustering

Neither document addresses computational complexity:

- `deduplicate_lessons()` compares each new lesson against all previously accepted rules: **O(n²)** worst case.
- `cluster_lessons()` runs pairwise `_related()` checks: explicit **O(n²)** loop.
- The proposed `cluster_lessons_by_similarity()` will also be O(n²) with connected-component union-find.

At 66 active lessons this is trivial. At 500+ lessons, ingestion and compaction will degrade noticeably. At 2000+, it becomes a performance bottleneck.

**Fix**: For the near-term (< 500 lessons), O(n²) is acceptable. For the future:
1. **Category blocking**: Only compare against lessons in the same or overlapping categories to partition the search space.
2. **Locality-Sensitive Hashing (LSH)** on token sets (MinHash) can reduce pairwise comparisons to O(n) amortized.
3. **Embedding ANN**: When sqlite-vec embeddings are populated, use approximate nearest-neighbor search as a candidate pre-filter.

### 4.2 Race Condition on Concurrent Pipeline Runs (TOCTOU)

The proposed ingestion guard does: (1) query pending + active lessons, (2) check similarity, (3) insert or merge. This is **not atomic**. If two concurrent pipeline runs both encounter the same failure, both will pass the similarity check and both will insert — creating duplicates.

**Fix**: Wrap the check-then-insert in an explicit SQLite transaction with `BEGIN IMMEDIATE` to serialize concurrent stage operations.

### 4.3 No Cross-Category Semantic Deduplication Strategy

Neither document addresses cross-category duplicates explicitly. A lesson categorized as `"ShellCheck"` with rule *"Always quote variables to prevent word splitting"* and a lesson categorized as `"Defensive Bash Scripting"` with rule *"Always quote variables to avoid word splitting"* are near-duplicates with different categories.

The proposed `cluster_lessons_by_similarity()` would catch these, but the ingestion guard must also perform **category-agnostic** similarity scans.

### 4.4 No Lesson Decay / Sunset Strategy

Both documents focus on preventing new duplicates and cleaning existing ones. Neither addresses **lesson decay** — what happens to lessons that are never retrieved, or reference patterns/tools that no longer exist.

**Fix**: Extend `flag_low_utility()` to also flag:
- `retrieval_count == 0` and `created` older than N days (never retrieved = never relevant)
- `ineffective_count / retrieval_count > 0.5` (consistently failed to prevent rework = potentially harmful)

Surface these in `localai-compact --dry-run` as "sunset candidates."

### 4.5 No Integration Test for the Full Lifecycle

Both documents have unit test plans but neither proposes an **integration test** that exercises the full path: `pipeline stage → stage_pending_lesson (dedup) → localai-compact → promote → lessons.md sync → prompt injection retrieval`. The bugs found were all cross-component interaction failures — exactly what integration tests catch.

### 4.6 Promotion Guard Doesn't Handle Write Amplification

The review doc (P1) proposes that when `is_new=False`, the caller does `write_all_lessons_to_markdown()` — a **full rewrite** of the entire `lessons.md` file. At 500+ lessons, this creates unnecessary write amplification on every reinforcement promotion.

**Fix**: Add a targeted `update_lesson_in_markdown()` function that patches only the affected lesson block in-place.

---

## 5. Summary Scorecard

| Dimension | Fix Doc | Review Doc |
|-----------|---------|------------|
| Root cause accuracy | ⭐⭐⭐⭐⭐ | N/A |
| Implemented solution quality | ⭐⭐⭐⭐ | N/A |
| Edge case identification | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Correctness of proposed solutions | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| ML/similarity limitations awareness | ⭐⭐ | ⭐⭐ |
| Scaling / performance awareness | ⭐ | ⭐ |
| Concurrency safety | ⭐ | ⭐ |
| Data lifecycle / decay | ⭐ | ⭐ |

---

## 6. Relationship to Implementation Stages

The findings in this analysis feed directly into the [staged implementation roadmap](stages-overview.md):

- **Stage 1** addresses all items from the fix doc, review doc, and the corrections/gaps in §3 and §4 of this analysis.
- **Stage 2A** addresses the embedding infrastructure needed to move beyond lexical-only similarity (§3.3).
- **Stage 2B** wires embeddings into the retrieval pipeline for hybrid search.
- **Stage 3** addresses semantic deduplication and the O(n²) scaling concerns (§4.1, §4.3).
