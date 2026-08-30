# Phase 4 Completion Report — Lesson Injection (Pipeline Read Path)

> **Status**: ✅ Complete
> **Completed**: 2026-08-29
> **Source plan**: [`memory_multi-phase_implementation_summary.md`](./memory_multi-phase_implementation_summary.md)
> **Approach**: Smallest-first, each sub-section independently testable (4.01–4.04).

---

## Summary

Phase 4 implemented the **read path** of the memory system: before the Author's first
iteration, the pipeline queries the memory store for lessons relevant to the current task
prompt and injects the top-K into the Author's context. It builds on the Phase 1
`MemoryStore` data layer (FTS5 keyword search) and adds embedding-based vector search via
`sqlite-vec`, closing the loop so that lessons promoted through the Phase 3 review gate are
actively reused to prevent rework.

---

## Deliverables by Sub-Section

### 4.01 — Injection Formatter ✅
Created [`sysadmin/mcp_core/injection.py`](../sysadmin/mcp_core/injection.py):
- `format_lessons_for_prompt(lessons: list[dict]) → str` — renders a `### Relevant Lessons from Past Runs` markdown section
- Each lesson rendered as a numbered block with rule text, category, and keywords
- Returns `""` when the lessons list is empty (no section header injected)
- Output is human-readable rule text only — no raw JSON

### 4.02 — Embedding Model Setup ✅
Created [`sysadmin/mcp_core/embeddings.py`](../sysadmin/mcp_core/embeddings.py):
- `get_embedding(text, model="nomic-embed-text") → list[float]` — calls Ollama's `/api/embed` HTTP endpoint directly (mirroring `mcp_ollama/server.py`'s `_http_request` pattern, since no embedding tool is exposed on the MCP server)
- Returns a float vector; raises `RuntimeError`/`ValueError` on failure
- Pulled `nomic-embed-text` (768-dim) via `ollama pull nomic-embed-text` and verified it produces embeddings

### 4.03 — Vector Search with `sqlite-vec` ✅
Modified [`sysadmin/mcp_core/memory.py`](../sysadmin/mcp_core/memory.py):
- Installed `sqlite-vec` in the sysadmin venv
- Added an `embeddings` BLOB column to the `lessons` table, with a guarded `ALTER TABLE ADD COLUMN` migration for pre-existing databases
- `insert_lesson()` now stores an embedding when provided (serialized as little-endian float32 BLOB)
- `search_lessons_vector(query_embedding, top_k=3) → list[dict]` — cosine similarity via `vec_distance_cosine`
- `search_lessons_hybrid(query_text, query_embedding, top_k=3) → list[dict]` — merges FTS5 BM25 + vector scores; degrades gracefully to FTS5-only when `sqlite-vec` is unavailable or no embedding is provided

### 4.04 — Pipeline Injection Hook & Tests ✅
Modified [`sysadmin/mcp_cli/commands/pipeline.py`](../sysadmin/mcp_cli/commands/pipeline.py):
- `revision_loop()` now calls `_inject_lessons()` before iteration 1
- `_inject_lessons()` extracts significant keywords from the prompt (stop-word filtered), searches memory per-keyword, and merges results ranked by match count — because `search_lessons` treats its query as a strict phrase, a full-sentence prompt would otherwise rarely match
- Prepends the formatted section to `current_prompt` via `format_lessons_for_prompt()`
- Tracks `injected_lessons` (list of lesson IDs) in the pipeline result dict
- Prints terminal banner `📚 Injected N relevant lessons from memory`
- No matches → no injection and no banner; failures are logged but never block the pipeline

---

## Acceptance Criteria Verification

| Sub-section | Criteria | Result |
|:---|:---|:---|
| 4.01 | 3 lessons produce a readable markdown section with 3 numbered blocks | ✅ |
| 4.01 | Empty list returns `""` | ✅ |
| 4.01 | Output contains no raw JSON — human-readable rule text only | ✅ |
| 4.02 | `ollama list` shows `nomic-embed-text` | ✅ |
| 4.02 | `get_embedding("test sentence")` returns a list of floats with length > 0 | ✅ (768-dim) |
| 4.02 | Function works from within `sysadmin/` import path | ✅ |
| 4.03 | Insert 5 lessons with embeddings; vector search returns the correct lesson first | ✅ |
| 4.03 | Hybrid search combines both signals (keyword + vector outranks single-signal) | ✅ |
| 4.03 | If `sqlite-vec` is not importable, `search_lessons_hybrid` degrades to FTS5-only | ✅ |
| 4.04 | A "heredoc delimiters" lesson is retrieved/injected when the prompt mentions "heredoc" | ✅ |
| 4.04 | Pipeline result includes `injected_lessons` list with matching IDs | ✅ |
| 4.04 | With zero lessons in the store, pipeline runs identically (no regression) | ✅ |
| 4.04 | Unit tests verify injection appears in the Author prompt | ✅ |

---

## Verification Commands

```bash
# Phase 4 unit tests (15 new tests across 3 files)
cd sysadmin && ./venv/bin/pytest tests/test_injection.py tests/test_memory.py tests/test_pipeline.py -v

# Full regression suite (97 passed, 1 skipped)
cd sysadmin && ./venv/bin/pytest tests/ -q

# Embedding smoke test (768-dim vector)
cd sysadmin && ./venv/bin/python -c "from mcp_core.embeddings import get_embedding; print(len(get_embedding('test sentence')))"

# sqlite-vec availability
cd sysadmin && ./venv/bin/python -c "import sqlite_vec; print('sqlite-vec OK')"
```

---

## Notes & Follow-ups

- **Embedding transport**: `get_embedding` talks directly to Ollama's `/api/embed` HTTP endpoint rather than through the MCP server, since no embedding tool is exposed there. This mirrors the existing `_http_request`/`OLLAMA_HOST` pattern in `server.py`.
- **Keyword-based injection**: `search_lessons` wraps its query as a strict FTS5 phrase, so `_inject_lessons` searches each significant prompt keyword individually and merges results ranked by match count. This recovers single-term relevance (e.g. "heredoc") from a full-sentence prompt.
- **Schema migration**: existing `.localai/memory.db` databases are migrated in place by adding the `embeddings` column on open; no data loss.
- **`sqlite-vec` installed**: the venv at `sysadmin/venv` now includes `sqlite-vec 0.1.9`. Note the venv's `pyvenv.cfg` points at the original `local-ai` checkout path; packages must be installed via `./venv/bin/python -m pip install ...` to land in the current `local-ai_vscodium` site-packages.
- Phase 4 depends on Phase 1 (data layer) and consumes the active `lessons` table populated by the Phase 3 review gate.
- Phase 5 (Retrieval Telemetry & Attribution) can now build on the `injected_lessons` tracking introduced in 4.04.
