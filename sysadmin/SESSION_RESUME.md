# Local AI Multi-Agent Pipeline: Session Summary & Resume Guide

**Date**: September 30, 2026  
**Status**: Arc-Orc-Rev Multi-Agent Pipeline Operational with Fast-Path & Dynamic Coder Escalation Cascade; Output Boundary & Atomic Synthesis Protection Enforced; Architect Confusion Gate Operational; Banned Stacked Negatives & Rebuilt 14 Modelfiles; Multi-Layer Lesson Deduplication Engine Active; 360 Unit/Integration Tests Passing Cleanly  
**Active Branch**: `feat/arc-orc-rev-pipeline`  

---

## 📌 Executive Summary of Accomplishments

### 1. Deterministic Pre-Filters & Context Store
- **[`sysadmin/validator.py`](./validator.py)**: Implemented deterministic pre-filters (Checks 1–5, 7, and 9) failing fast on invalid schemas, missing tools/agents, invalid domain tags, DAG cycles, prompt tampering, or substandard cognition blocks (< 30 chars).
- **[`sysadmin/mcp_core/context_store.py`](./mcp_core/context_store.py)**: Implemented dual-layer context storage with plain JSON during active runs and `.tar.zst` lossless compression upon completion, with single-member streaming extraction.

### 2. Arc-Orc-Rev Multi-Agent State Machine ([`sysadmin/pipeline.py`](./pipeline.py))
- Operational state machine driving all 6 canonical horizontal cognitive roles:
  1. **Architect**: High-level task decomposition, risk analysis, and architectural guidance.
  2. **Orchestrator**: Concrete DAG generation, task dependency mapping, and model assignment.
  3. **Reviewer Gate**: Deterministic pre-filter validation + LLM semantic plan audit.
  4. **Security Gate**: STRIDE threat modeling, privilege isolation, and network safety checks.
  5. **Coder**: Pre-execution code authoring via `write_file` and multi-tier code gates.
  6. **Sysadmin**: Sandboxed execution in `terminal-mcp` (PTY session) with zero uninspected code execution.
- **Resumable Checkpoints**: State persistence in `runs/<run_id>/state.json` with `--resume <run_id>` support.

### 3. Pre-Execution Code Gates (Three-Tier Defense)
- **Tier 1 (Linter Gate)**: Deterministic ShellCheck static analysis, `set -euo pipefail` enforcement, and `ERR` diagnostic trap validation.
- **Tier 2A (Reviewer Code Gate)**: LLM prompt fidelity and acceptance criteria audit (`sysadmin/prompts/roles/reviewer_code.md`).
- **Tier 2B (Security Code Gate)**: LLM STRIDE behavioral safety audit (`sysadmin/prompts/roles/security_code.md`) ensuring no unprivileged escalation, binary tampering, or dangerous side effects.
- **Strict Role Boundaries**: Coder authors code and passes gates; execution is strictly delegated to `sysadmin` (eliminates duplicate/premature script executions).

### 4. Interactive Pipeline TUI (`pipeline_tui`)
- **6-Role Visual Stepper ([`widgets/stepper.py`](./pipeline_tui/widgets/stepper.py))**:
  - Restored `Coder` stage to complete the canonical 6-role flow: `Architect` ➔ `Orchestrator` ➔ `Reviewer` ➔ `Security` ➔ `Coder` ➔ `Sysadmin`.
  - Normalized stage aliasing in [`state.py`](./pipeline_tui/state.py) (`coder`/`author` ➔ `coder`, `dispatch`/`execute` ➔ `sysadmin`).
- **Code Synthesis Inspection ([`widgets/pillars_view.py`](./pipeline_tui/widgets/pillars_view.py))**:
  - Automatically switches to the `tab-code` viewer when advancing to or selecting the `coder` stage, surfacing generated script artifacts and diffs.
- **Real-Time Active Thinking Stream ([`widgets/thinking_view.py`](./pipeline_tui/widgets/thinking_view.py))**:
  - Live streaming of raw `<think>` deliberation tokens into the active thinking drawer.
  - Added stage metadata tracking in [`mcp_core/events.py`](./mcp_core/events.py) to associate thinking chunks with their corresponding role.
- **Resilient Run Discovery & Fault Detection ([`discovery.py`](./pipeline_tui/discovery.py))**:
  - Deduplicated live `.localai/runs/run-*.jsonl` event streams against persistent `traj-*` records using `task_file` run ID mapping, preventing duplicate entries in the run browser.
  - Deep event stream inspection: scans execution logs for non-zero exit codes (`Exit Code: 1`, `No such file or directory`) and marks abandoned/stale runs (>120s with no `pipeline_end`) accurately as `"failed"` rather than `"in_progress"`.
- **Dynamic Cognitive Pillars & Telemetry Fix ([`widgets/pillars_view.py`](./pipeline_tui/widgets/pillars_view.py), [`pipeline.py`](./pipeline.py))**:
  - Rewrote `CognitivePillarsView.update_state()` to dynamically pull `stage_reasoning` directly for the active selected stage (`Architect`, `Orchestrator`, `Reviewer`, `Security`, `Coder`, `Sysadmin`), rendering role-specific Strategy, Risks, Solution, and Verification Plan.
  - Enhanced `pipeline.py` to extract synthesized code from JSON `outputs` dictionaries and emit `code_synthesized` events in real-time.
  - Added missing `linter_result` and `review_result` event emissions to `pipeline.py` during pre-execution code gates, fully populating the `Critique & Lint` drawer tab.
  - Added backward-compatible event reconstruction in `discovery.py::load_events_for_run()` to backfill code synthesis and linter findings when loading past runs.
- **Adaptive Drawer Layout & Thinking Flex ([`widgets/thinking_view.py`](./pipeline_tui/widgets/thinking_view.py), [`widgets/pillars_view.py`](./pipeline_tui/widgets/pillars_view.py))**:
  - Configured `ActiveThinkingView` to flex-grow with `height: 1fr; min-height: 6;` so window resizing expands the active chain-of-thought stream.
  - Set `CognitivePillarsView` to a balanced fixed height (`height: 13; min-height: 8;`), keeping the tabbed interface structured without absorbing window height.
- **Clean Event Loop Teardown ([`app.py`](./pipeline_tui/app.py))**:
  - Replaced infinite background poll loops with `self.is_running` checks in Textual worker tasks (`_tail_new_runs` and `_tail_events`), eliminating test-runner hangs and memory leaks.

### 5. Universal Raw `<think>` Deliberation Prompts & Modelfiles
- Updated canonical role prompts for ALL pipeline roles:
  - [`architect.md`](./prompts/roles/architect.md), [`orchestrator.md`](./prompts/roles/orchestrator.md), [`reviewer.md`](./prompts/roles/reviewer.md), [`security.md`](./prompts/roles/security.md), [`reviewer_code.md`](./prompts/roles/reviewer_code.md), [`security_code.md`](./prompts/roles/security_code.md), [`coder.md`](./prompts/roles/coder.md), and [`sysadmin.md`](./prompts/roles/sysadmin.md).
- Standardized two-step execution pattern: first emit raw `<think>...</think>` engineering/operational deliberation (edge cases, defensive invariants, traps, and validation assertions), followed by the valid schema JSON object (`PlanMessage`, `ReviewVerdict`, `ExecutionResult`, etc.).
- Preserved clean code extraction: `pipeline.py` safely extracts `<think>` blocks into `cognition.chain_of_thought` and emits them to `ActiveThinkingView` and `terminal-mcp`, while code is isolated cleanly within JSON outputs.
- Synchronized Modelfiles across tiers (`8gb`, `16gb`, `24gb`): Updated default `SYSTEM` prompts in `Modelfile-prime-*`, `Modelfile-coder-*`, and `Modelfile-sysadmin-*` to prescribe raw `<think>` deliberation prior to structured output for standalone interactive sessions as well.

### 6. Context Window Lessons Injection Fix & Emitter Telemetry
- Resolved hardcoded empty `lessons=[]` in [`sysadmin/pipeline.py`](./pipeline.py)`::stage_chat()`. Injected lessons are now passed dynamically to `emitter.context_window(..., lessons=relevant_lessons)`.
- Updated telemetry reporting in [`sysadmin/pipeline.py`](./pipeline.py) and [`sysadmin/mcp_cli/commands/pipeline.py`](./mcp_cli/commands/pipeline.py) to display the active role alongside the model.

### 7. Local-Ollama MCP Server Pipeline Tools
- **Registered Tools**: Added `run_pipeline` and `process_prompt` to [`sysadmin/mcp_ollama/server.py`](./mcp_ollama/server.py).
- **Stdio Protocol Protection**: Redirected stdout banners to `sys.stderr` via `contextlib.redirect_stdout(sys.stderr)` and updated `send_terminal_mcp` in [`sysadmin/mcp_core/transport.py`](./mcp_core/transport.py) so JSON-RPC stdio protocol is never corrupted.
- **Documentation**: Documented tool schemas in [`sysadmin/mcp_ollama/README.md`](./mcp_ollama/README.md).

### 8. Pipeline CLI Entrypoint & Shell Aliases
- **CLI Runner Updates ([`pipeline.py`](./pipeline.py))**:
  - Added `--tier {8gb,16gb,24gb}` support resolving default `winter-prime:<tier>` models.
  - Added `--keep-models` and `--unload-models` flags for runtime compatibility.
  - Passed `tier` dynamically to `emitter.pipeline_start` for telemetry.
- **Standalone Binary ([`bin/localai-pipeline`](../bin/localai-pipeline))**:
  - Created executable entrypoint wrapping `sysadmin/pipeline.py` with explicit venv isolation.
- **Shell Aliases ([`sysadmin/shell_aliases.sh`](./shell_aliases.sh))**:
  - Updated `localai-pipeline` to invoke `${LOCAL_AI_DIR}/bin/localai-pipeline`.
  - Updated tier variants: `localai-pipeline-8gb`, `localai-pipeline-16gb`, `localai-pipeline-24gb`.
  - Preserved legacy 4-phase runner under `localai-pipeline-legacy`.

### 9. Lesson Invariant Linter & Safety Verifier
- **Deterministic Invariant Linter ([`mcp_core/lesson_linter.py`](./mcp_core/lesson_linter.py))**:
  - Implemented 5 deterministic rule suites: `TOOL_CONTRACT` (e.g. anti-write_file), `ANTI_SAFEGUARD` (disregard safeguards, set +e, trap - ERR), `TEST_SUBVERSION` (testing to pass vs catch errors, fake assertions), `DESTRUCTIVE_COMMAND` (rm -rf /, chmod 777, force push), and `ENVIRONMENT` (hardcoded paths, ambient path, polling loops).
  - Provided `lint_lesson()` and `lint_all_lessons()` with `CRITICAL` and `WARNING` severity categorization.
- **Git-Canonical Markdown Parser ([`mcp_core/lessons_writer.py`](./mcp_core/lessons_writer.py))**:
  - Implemented `parse_lessons_from_markdown()` to parse YAML-frontmatter lessons directly from `lessons.md`.
  - Merged SQLite and Markdown stores in `LintLessonsCommand` to guarantee dual-store parity and ensure restored or hand-edited lessons are never bypassed.
- **CLI Invariant Scanner ([`mcp_cli/commands/lint_lessons.py`](./mcp_cli/commands/lint_lessons.py))**:
  - Added `lint-lessons` subcommand with `--fix` interactive remediation (`[d] Delete`, `[m] Modify`, `[s] Skip`).
  - Added safe wiki refresh targeting explicit files (`dashboard.md`, `index.md`, `log.md`), preventing directory write errors.
  - Successfully remediated and purged `lesson-20260830-01` (anti-write_file anti-pattern); updated Rule #1 provenance in [`sysadmin/prompts/SYSTEM_RULES.md`](./prompts/SYSTEM_RULES.md) to link to `lesson-20260830-03`.
- **Workflow Protection & Warnings ([`mcp_cli/commands/memory.py`](./mcp_cli/commands/memory.py))**:
  - Integrated invariant check into `review-lessons` review cards to flag dangerous or invalid pending lessons *before* promotion.
  - Integrated invariant check into `audit-lessons` to surface active violating lessons.
- **Shell Aliases ([`sysadmin/shell_aliases.sh`](./shell_aliases.sh))**:
  - Added `localai-lint-lessons` and `localai-lint-lessons-fix`.

### 10. Dynamic Dual-Model Critic Selection (24GB Residency)
- **Architect & Orchestrator Dynamic Selection**:
  - Added support for `auditor_strategy` (`"balanced"` ➔ `qwen3:8b`, `"adversarial"` ➔ `deepseek-r1:8b`, `"algorithmic"` ➔ `deepseek-coder-v2:16b`) and `auditor_model`.
  - Updated role prompts: [`architect.md`](./prompts/roles/architect.md) and [`orchestrator.md`](./prompts/roles/orchestrator.md).
- **Deterministic Check 10 & Anti-Self-Review Invariant ([`validator.py`](./validator.py))**:
  - Validates `auditor_strategy` values.
  - Enforces `Rule R-AUDIT-01`: the critic cannot be identical to the builder model (`auditor_model != builder_model`).
- **CLI & MCP Tooling ([`pipeline.py`](./pipeline.py), [`mcp_ollama/server.py`](./mcp_ollama/server.py))**:
  - Added `--dual-model` (auto-resolves 24GB tier) and `--dynamic-auditor` CLI flags.
  - Updated MCP server tool `run_pipeline` with `dual_model` and `dynamic_auditor` parameters.
- **Architecture Documentation ([`DUAL_MODEL_24GB_SETUP_GUIDE.md`](../ollama_update/customized_models/DUAL_MODEL_24GB_SETUP_GUIDE.md))**:
  - Added Section 5 detailing Dynamic Auditor Selection, strategy mappings, VRAM allocation math, and concurrency configurations.

### 11. Pipeline Live Execution Safety & Error Gate Enforcement
- **Accurate PTY Return Code Extraction ([`mcp_ollama/server.py`](./mcp_ollama/server.py))**:
  - Updated `_execute_in_terminal_mcp` to execute commands with a sentinel exit marker (`__LOCALAI_EXIT:$?__`), capturing the real subshell return code rather than hardcoding `0`.
  - Implemented `AGENTS.md` Rule 2 safety override: buffer inspection forces a non-zero exit code if unhandled error markers (`❌ [ERROR]`, `Traceback`, `command not found`, `No such file or directory`) exist in stdout.
- **Fail-Fast Verification Gates & Abort Handling ([`pipeline.py`](./pipeline.py))**:
  - If a task fails pre-execution code gates after retries, `run_dispatch` marks `state.status = "aborted"` and halts dispatch immediately.
  - Added dual-channel script execution validation checking both exit code and diagnostic error signatures.
  - Added post-dispatch sanity check to prevent false-positive completion if any DAG tasks failed.

### 12. Self-Contained Run Capture & Query-Once Context Window Caching
- **Self-Contained Run Capture ([`mcp_core/events.py`](./mcp_core/events.py), [`pipeline.py`](./pipeline.py))**:
  - `pipeline_start` records explicit `context_limits` mapping each model to its true context size.
  - Replay and inspection directly read stored ground-truth values without requiring live Ollama queries.
- **Query-Once-and-Remember Model Context Cache ([`pipeline_tui/state.py`](./pipeline_tui/state.py))**:
  - Stored `model_context_limits` dictionary in `PipelineState`.
  - `get_context_limit(stage)` checks captured event data first, cached model limits second, queries Ollama once for newly encountered models third, and falls back to tier default fourth.
  - Fixed `ContextWindowDrawer` mount NameError bug and enabled exact context window limit display across 16GB and 24GB tiers.

### 13. Verification & Knowledge Graph
- **360 Passing Unit/Integration Tests**: Full test suite across `sysadmin/tests/` passing cleanly.
- **AST Knowledge Graph Synchronized**: Updated via `graphify update .` (2,552 nodes, 4,641 edges, 177 communities).

### 14. Interactive Lessons TUI & Compact Review Queue
- **Interactive Lessons TUI ([`sysadmin/lessons_tui/`](./lessons_tui/))**:
  - Full Textual dashboard for browsing, filtering, and editing active lessons in SQLite and Markdown.
  - Resolved event collision on list selection (`ListView.Selected`) and added auto-safe review mode.
- **Clustered Pending Lessons Compact Queue ([`bin/localai-compact-queue`](../bin/localai-compact-queue), [`compact_app.py`](./lessons_tui/compact_app.py))**:
  - Implemented compact queue TUI for batch-triaging semantically clustered pending lessons.

### 15. Fast-Path & Dynamic Coder Model Escalation Cascade
- **Fast-Path Runner ([`sysadmin/pipeline.py`](./pipeline.py))**:
  - Direct single-step execution commands route via fast-path, bypassing full DAG decomposition while preserving verification gates.
- **VRAM-Aware Coder Model Escalation Cascade**:
  - Dynamically escalates coder models upon retries across 3 stages per tier:
    - **8GB Tier**: `winter-coder:8gb` ➔ `winter-coder:8gb-deepseek` ➔ `winter-prime:8gb`
    - **16GB Tier**: `winter-coder:16gb` ➔ `winter-coder:16gb-deepseek` ➔ `winter-prime:16gb`
    - **24GB Tier**: `winter-coder:24gb` ➔ `winter-coder:24gb-codestral` ➔ `winter-prime:24gb`
  - Replaced raw upstream Qwen base models with Winter customized/fine-tuned models for consistent system instructions.
  - Added configurable `--retry-budget` (1 to 15, default: 3) and `--escalation-threshold`.
- **Domain-Aware Model Performance Tracking**:
  - Added `record_model_attempt()` in `MemoryStore`, recording success/retry metrics partitioned by domain tags.

### 16. Output Boundary Protection & Atomic Script Synthesis
- **Output Guard & Fuzzy Path Matching ([`sysadmin/pipeline.py`](./pipeline.py))**:
  - Rejects undeclared file writes emitted by models.
  - Accommodates relative vs absolute paths and basename matching so minor model path formatting differences don't trigger false-positive file drops.
- **Pre-Execution Code Output Gate**:
  - If a coder model fails to emit declared files in `outputs` or emits unstructured text, triggers structured format remediation rather than silently passing execution.

### 17. Defensive Standards Alignment & Modelfile Rebuilds (Ban Stacked Negatives)
- **Architect Pre-Flight Confusion Gate**:
  - Pre-flight review in `run_architect` bailing out early if user prompt contains confusing or contradictory statements.
- **Elimination of Inverted Bash Negation**:
  - Replaced inverted error testing (`if ! cmd 2>/dev/null; then exit 1; fi`) with positive fault-detection pattern:
    `if cmd >/dev/null 2>&1; then echo "❌ Failed to detect error"; exit 1; fi`.
  - Updated [`AGENTS.md`](../AGENTS.md), [`SYSTEM_RULES.md`](./prompts/SYSTEM_RULES.md), [`roles/coder.md`](./prompts/roles/coder.md), and [`verify_code_quality_toolchain.md`](./prompts/verify_code_quality_toolchain.md).
- **Modelfile Synchronization & Rebuild ([`build_models.sh`](../ollama_update/customized_models/build_models.sh))**:
  - Patched 14 customized Modelfiles across 8GB, 16GB, and 24GB tiers.
  - Enhanced `build_models.sh` with `updated` target and individual modelfile targeting.
  - Rebuilt all 14 models and aliases in Ollama (`winter-coder:*`, `winter-reviewer:*`, `winter-prime:*`, and `winter-coder:8gb-trained`).

### 18. Multi-Layer Lesson Deduplication Engine
- **Normalization & Pruning Core ([`mcp_core/injection.py`](./mcp_core/injection.py))**:
  - Implemented `normalize_lesson_rule()` (whitespace collapse, lowercase, punctuation stripping) and `deduplicate_lessons()`.
  - `format_lessons_for_prompt()` automatically deduplicates before generating prompt headers.
- **Store-Level Deduplication ([`mcp_core/memory.py`](./mcp_core/memory.py))**:
  - Added `dedup: bool = True` across `search_lessons()`, `search_lessons_vector()`, and `search_lessons_hybrid()`.
  - Expanded candidate fetch limits (`max(top_k * 4, 12)`) to prevent duplicate clusters from depleting `top_k`.
- **Pipeline Aggregation Standardized ([`sysadmin/pipeline.py`](./pipeline.py), [`mcp_cli/commands/pipeline.py`](./mcp_cli/commands/pipeline.py))**:
  - Standardized all 5 pipeline phases to use `collect_relevant_lessons()`, preventing duplicate rule accumulation across phase tags.
### 19. Near-Duplicate & Semantic Phrasing Lesson Deduplication
- **Root Cause Analysis (`run-20260930-054329-169356`)**:
  - Investigation of `.localai/runs/run-20260930-054329-169356.jsonl` revealed the Orchestrator received both `lesson-20260918-44` (*"All pipeline runs that receive an 'audit pass' with 'no risks' should be automatically approved."*) and `lesson-20260918-10` (*"All pipeline runs that receive an 'audit pass' with no reported risks should be automatically approved."*).
  - Exact string normalization (`normalize_lesson_rule`) only removed punctuation and collapsed whitespace, failing on minor phrasing variations (e.g. `"with 'no risks'"` vs `"with no reported risks"`).
  - Similarly, the Reviewer stage was injected with `lesson-20260918-11` and `lesson-20260918-25` (*"with no identified risks"* vs *"with no risks"*).
- **Fuzzy & Token Jaccard Similarity Engine ([`mcp_core/injection.py`](./mcp_core/injection.py))**:
  - Added `are_rules_similar(rule1, rule2, threshold=0.75)` combining word-level Jaccard similarity and character-level `difflib.SequenceMatcher` ratio.
  - Guarded against false positives on short test labels (`"Rule A"` vs `"Rule C"`, `"bash lesson 0"` vs `"bash lesson 1"`) by requiring significant token overlap (`jaccard >= 0.75` and `ratio >= 0.70`) or overwhelmingly high character match on longer rules (`ratio >= 0.92`, length > 25).
  - Enhanced `deduplicate_lessons()` to evaluate all incoming rules against previously accepted candidates using `are_rules_similar()`, retaining the highest-utility rule and dropping semantic duplicates.
- **Pipeline Collection Headroom & Delegation ([`sysadmin/pipeline.py`](./pipeline.py))**:
  - Refactored `collect_relevant_lessons()` to query candidate pools with headroom (`max(top_k * 3, 10)`) and delegate all deduplication to `deduplicate_lessons()`, ensuring near-duplicate pruning does not prematurely starve `top_k` results.
- **Verification ([`sysadmin/tests/test_injection.py`](./tests/test_injection.py))**:
  - Added unit tests specifically verifying that `lesson-20260918-44`/`lesson-20260918-10` and `lesson-20260918-11`/`lesson-20260918-25` pairs are deduplicated, while distinct rules remain unpruned. All 363 tests in repository pass cleanly.

---

## ⏸️ Current State at Pause

- **Working Tree**: All components implemented, tested, and verified on branch `feat/arc-orc-rev-pipeline`.
- **TUI & Runner**: Fully functional with live monitoring, replay capabilities, and updated `localai-pipeline` aliases.
- **MCP Server Registration**: `local-ollama` is configured in `~/.gemini/config/mcp_config.json` with `run_pipeline`, `process_prompt`, and `inspect_pipeline_run`.
- **Target Test Prompt**: [`sysadmin/prompts/hello_world_test.md`](./prompts/hello_world_test.md) and [`sysadmin/prompts/verify_code_quality_toolchain.md`](./prompts/verify_code_quality_toolchain.md) ready for execution.

---

## 🚀 How to Resume Work (Immediate Next Steps)

1. **Launch Live TUI Monitoring**:
   Open a dedicated terminal and start the interactive TUI:
   ```bash
   localai-watch
   # or: bin/pipeline-watch
   ```
2. **Execute Multi-Agent Pipeline Run**:
   In another terminal or via the IDE MCP tool (`call_mcp_tool`), trigger a pipeline execution:
   ```bash
   localai-pipeline sysadmin/prompts/hello_world_test.md
   # or for specific tiers:
   localai-pipeline-8gb sysadmin/prompts/hello_world_test.md
   ```
3. **Observe Execution in TUI**:
   - Verify 6-stage progression: `Architect` ➔ `Orchestrator` ➔ `Reviewer` ➔ `Security` ➔ `Coder` ➔ `Sysadmin`.
   - Inspect streaming `<think>` tokens in the active thinking drawer.
   - Inspect synthesized bash code in `tab-code` during the Coder stage.
   - Verify live execution in the terminal drawer.
4. **Inspect Trajectory & Memory**:
   - Check trajectory record in [`sysadmin/data/trajectories.jsonl`](./data/trajectories.jsonl).
   - Check cognitive memory updates in [`sysadmin/data/memory.db`](./data/memory.db).
5. **Prepare PR**:
   Open a pull request from `feat/arc-orc-rev-pipeline` for human review.

---

## 📂 Key Files Reference
* **Session Resume Document**: [`sysadmin/SESSION_RESUME.md`](./SESSION_RESUME.md)
* **Pipeline Runner**: [`sysadmin/pipeline.py`](./pipeline.py)
* **Pipeline TUI App**: [`sysadmin/pipeline_tui/app.py`](./pipeline_tui/app.py)
* **TUI Stepper Widget**: [`sysadmin/pipeline_tui/widgets/stepper.py`](./pipeline_tui/widgets/stepper.py)
* **TUI Thinking Drawer**: [`sysadmin/pipeline_tui/widgets/thinking_view.py`](./pipeline_tui/widgets/thinking_view.py)
* **TUI Discovery Engine**: [`sysadmin/pipeline_tui/discovery.py`](./pipeline_tui/discovery.py)
* **MCP Server**: [`sysadmin/mcp_ollama/server.py`](./mcp_ollama/server.py)
* **Role System Prompts**: [`sysadmin/prompts/roles/`](./prompts/roles/)
* **Lesson Invariant Linter Core**: [`sysadmin/mcp_core/lesson_linter.py`](./mcp_core/lesson_linter.py)
* **Lesson Linter CLI**: [`sysadmin/mcp_cli/commands/lint_lessons.py`](./mcp_cli/commands/lint_lessons.py)
* **Lesson Duplication & Queue Deduplication Design**: [`docs/fix-lesson-duplication-detection.md`](../docs/fix-lesson-duplication-detection.md)
* **Test Suite**: [`sysadmin/tests/`](./tests/)
