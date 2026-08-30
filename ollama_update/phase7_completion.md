# Phase 7 Completion Report — Trajectory Recording & Wiki Dashboard

> **Status**: ✅ Complete
> **Completed**: 2026-08-30
> **Source plan**: [`memory_multi-phase_implementation_summary.md`](./memory_multi-phase_implementation_summary.md)
> **Approach**: Smallest-first, each sub-section independently testable (7.01–7.05).

---

## Summary

Phase 7 closes the memory system: it records rejected/approved script pairs from
multi-iteration pipeline runs as JSONL trajectories (for future fine-tuning data),
and generates a human-readable Obsidian wiki dashboard of memory health. It builds
on the telemetry counters from Phase 5 and the clustering/flagging utilities from
Phase 6.

---

## Deliverables by Sub-Section

### 7.01 — Trajectory Recorder (Pipeline Hook) ✅
Created [`sysadmin/mcp_core/trajectories.py`](../sysadmin/mcp_core/trajectories.py):
- `record_trajectory(pipeline_result, prompt_content, trajectories_path=None, raw_dir=None, task_file="") -> str` — appends one JSON line to `sysadmin/data/trajectories.jsonl` and returns the trajectory ID
- Record fields: `id`, `timestamp`, `task_file`, `injected_lessons`, `reviewer_critique`, `iterations`, `outcome` (`approved` / `failed` / `aborted`), plus tiered payload fields
- Modified [`sysadmin/mcp_cli/commands/pipeline.py`](../sysadmin/mcp_cli/commands/pipeline.py):
  - `revision_loop()` now accumulates `script_versions` (each iteration's sanitized script, oldest→newest) and exposes it in the result dict
  - New `_record_trajectory_if_rework()` hook called from `run()` alongside lesson staging — records only when `iterations > 1`; failures are logged but never block the pipeline

### 7.02 — Tiered Schema (Inline vs. Diff+Ref) ✅
In [`sysadmin/mcp_core/trajectories.py`](../sysadmin/mcp_core/trajectories.py):
- **Tier 1** (`chosen` < 150 lines): `payload_type="inline"`, `rejected` + `chosen` stored inline as strings; `diff`/`focused_snippet`/`raw_dir` = null
- **Tier 2** (`chosen` ≥ 150 lines): `payload_type="diff_and_ref"`; `diff` (unified via `difflib.unified_diff`) + `focused_snippet` stored inline; verbatim `rejected.sh`/`chosen.sh` offloaded to `sysadmin/data/raw_trajectories/<id>/`; `raw_dir` records the workspace-relative path
- `focused_snippet`: ±15 lines around the first line of `chosen` matching a reviewer-critique keyword; falls back to the first 30 lines when no keyword matches

### 7.03 — Wiki Index Generator ✅
Created [`sysadmin/mcp_core/wiki.py`](../sysadmin/mcp_core/wiki.py):
- `generate_index(lessons, output_path) -> None` — groups lessons by category into markdown tables; each row: lesson ID (Obsidian `[[id]]` link), keywords, rule summary (truncated ~60 chars), source task, created date
- Empty lesson list → `# Lesson Index` + `No lessons recorded.`

### 7.04 — Wiki Dashboard Generator ✅
In [`sysadmin/mcp_core/wiki.py`](../sysadmin/mcp_core/wiki.py):
- `generate_dashboard(lessons, output_path) -> None` — sections: Top-Retrieved, Highest-Utility, Promotion Candidates (via `cluster_lessons`), Low-Utility Flags (via `flag_low_utility`); includes `retrieval_count`, `prevention_ratio`, `utility_score`
- `generate_log(events, output_path) -> None` — append-only chronological entries to `ollama_update/wiki/log.md`

### 7.05 — `compile-wiki` CLI & Tests ✅
Modified [`sysadmin/mcp_cli/commands/memory.py`](../sysadmin/mcp_cli/commands/memory.py):
- New `CompileWikiCommand` (`@command`, name `compile-wiki`) — loads all lessons from `MemoryStore`, creates `ollama_update/wiki/`, calls `generate_index()`, `generate_dashboard()`, `generate_log()`
- Prints summary: `📚 Wiki compiled: index.md (N lessons), dashboard.md, log.md`

---

## Acceptance Criteria Verification

| Sub-section | Criteria | Result |
|:---|:---|:---|
| 7.01 | After a 2-iteration pipeline run, `trajectories.jsonl` gains one new line | ✅ |
| 7.01 | Record contains valid JSON parseable by `json.loads()` | ✅ |
| 7.01 | Iteration-1 passes do not produce trajectory records | ✅ |
| 7.02 | A 50-line script stores inline (`payload_type="inline"`, `rejected` + `chosen` present) | ✅ |
| 7.02 | A 200-line script stores diff+ref (`payload_type="diff_and_ref"`, `diff` + `focused_snippet` present, raw files in subdirectory) | ✅ |
| 7.02 | Diff is a valid unified diff format | ✅ |
| 7.03 | 10 lessons across 3 categories produce a markdown file with 3 tables | ✅ |
| 7.03 | Empty lesson list produces a valid file with "No lessons recorded" message | ✅ |
| 7.03 | Output is valid markdown | ✅ |
| 7.04 | Dashboard with 10 lessons produces readable leaderboard tables | ✅ |
| 7.04 | Log entries are append-only (running twice doesn't overwrite previous entries) | ✅ |
| 7.04 | Valid markdown viewable in Obsidian | ✅ |
| 7.05 | `compile-wiki` generates all three files | ✅ |
| 7.05 | Running twice updates files without corruption | ✅ |
| 7.05 | Unit tests verify output file contents with synthetic lesson data | ✅ |

---

## Verification Commands

```bash
# Phase 7 unit tests (22 new tests across 4 files)
cd sysadmin && ./venv/bin/pytest tests/test_trajectories.py tests/test_wiki.py \
  tests/test_compile_wiki.py tests/test_pipeline.py tests/test_cli.py -v

# Full regression suite (164 passed, 1 skipped)
cd sysadmin && ./venv/bin/pytest tests/ -q

# CLI registration + run
cd sysadmin && ./venv/bin/python mcp_client.py --help | grep compile-wiki
cd sysadmin && ./venv/bin/python mcp_client.py compile-wiki
```

---

## Notes & Follow-ups

- **Version tracking**: `revision_loop` previously kept only `final_code_block`. Phase 7 added `script_versions` (list of each iteration's script) so trajectories can capture `rejected` (all but the last) and `chosen` (last). This is a backward-compatible additive change — existing consumers (`_apply_telemetry`, `_stage_lesson_if_rework`, `execute`) are unaffected.
- **Trajectory gating**: the pipeline hook records only when `iterations > 1`. Iteration-1 passes produce no trajectory (per the acceptance criteria).
- **Tier threshold**: 150 lines. Small scripts stay fully inline for easy inspection; large scripts store a compact diff + focused snippet and offload verbatim files to `sysadmin/data/raw_trajectories/<id>/`.
- **Wiki output**: `ollama_update/wiki/{index,dashboard,log}.md` are generated by `compile-wiki`. `log.md` is append-only — running `compile-wiki` twice appends a second event without overwriting.
- Phase 7 depends on Phase 2 (trajectory recording hook) and Phase 5/6 (telemetry + clustering/flagging for the dashboard).
- This completes all 7 phases of the AI Memory System implementation outline.
