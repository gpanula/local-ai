# Agent Workspace Rules

## 1. Git & Workflow
- **No `main` commits**: Use branch prefixes `feat/`, `fix/`, `docs/`, `exp/`. Open PR for human review.
- **Gitmoji commits**: Format `<gitmoji> [scope]: <desc>`. Check `CONTRIBUTING.md` / gitmoji.dev.
- **Author**: Use repo local config (`smurf-frank <frank@grumpy.smurf.work>`).
- **GitHub CLI**: Use `direnv` scoped environment (`.git/credentials`). Do NOT touch `~/.config/gh/hosts.yml`.

## 2. Safety & Scripting
- **SysAdmin**: Dry-run / check-mode first. Non-destructive inspections.
- **Terminal MCP**: Never rely solely on `exit 0`. Inspect buffer via `getContent`/logs for hidden tracebacks or permission faults.
- **Bash standard**:
  - Headers: `set -euo pipefail`
  - Trap err: `trap 'echo "❌ [ERROR] Line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR`
  - Trap exit: `trap 'rm -rf "${TMP_DIR:-}"' EXIT`
  - Temp dirs: Explicit `mktemp -d -p /tmp` (never assume `$TMPDIR` exists).
  - Assertions: Check `[ -x "${BIN}" ]` before success banners. Never print success on failed assertions.
  - Venv & Binary Isolation: Never rely on ambient `$PATH`. Deterministically resolve virtual envs (`VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"`) and invoke tools via explicit paths (`"${VENV_DIR}/bin/<binary>"`).

## 3. Security & Cleanliness
- **Secrets**: Never commit/log keys, tokens, passwords. Use `$GH_TOKEN`, `$OLLAMA_HOST`, or git-ignored files.
- **Sanitization**: No hardcoded `/home/<user>`. Use `~`, `$HOME`, or relative workspace paths.
- **Readability**: Avoid multi-line `python -c` in tool calls. Wrap logic in `sysadmin/*.py` scripts.

## 4. Execution & Boundaries
- **No Polling**: No `sleep`/`ollama ps` polling loops. Launch async tasks, yield tool calls, wait for reactive notifications.
- **Terminal MCP Visibility**: Output live progress and interactive script execution to the active `terminal-mcp` session.
- **Execution Modes**:
  - ⚡ **Direct Dev Mode** *(Default for infrastructure, tooling, memory/lessons, modelfiles, scripts, and dataset engineering)*:
    - Antigravity directly authors, patches, and tests code (`sysadmin/*.py`, `sysadmin/*.sh`, modelfiles, datasets, unit tests) for fast iteration.
  - 🤖 **Pipeline Delegation Mode** *(Activated explicitly by keywords: `"run pipeline"`, `"delegate"`, `"test local ai"`)*:
    - Antigravity writes the prompt spec (`sysadmin/prompts/*.md`); awaits human review approval; then delegates execution to the local Ollama multi-agent pipeline.
    - **Delegation Convention**: When directed to run or execute the pipeline, immediately invoke the native MCP tool `call_mcp_tool('local-ollama', 'run_pipeline', ...)` with `async_run=True` (or as specified) directly without pre-inspecting server or pipeline source files. The MCP server is self-documenting (via parameter descriptions and `help="<param>"`).
- **Prompt Specification Standards (`sysadmin/prompts/*.md`)**:
  - **Ban Stacked Negatives**: Never use phrasing like "validate negative error detection", "verify failures are handled", or "negative syntax checking". Use direct positive terms: **"Fault Detection"** or **"Error Catching"**.
  - **Specify Exit Codes Directly**: Every test suite in Section 2 MUST explicitly state expected process exit boundaries (e.g. *“Malformed input must exit non-zero; valid input must exit 0”*).
  - **Provide Direct Assertion Pattern**: In Section 3 Defensive Standards, ALWAYS mandate testing error-catching directly without bash negation:
    `if command >/dev/null 2>&1; then echo "❌ Failed to detect error"; exit 1; fi`

## 5. Observability & Local AI Transparency
- **Full Model Transparency**: When executing or querying local Ollama models (`ollama_chat`, `ollama_task_agent`, `build-and-run`, `pipeline-run`), prioritize full visibility. Never truncate, mute, or suppress the local model's reasoning, chain-of-thought, or structured tool calls.
- **Local Learning & Dataset Research**: Local models run on self-hosted hardware for learning, evaluation, and fine-tuning. Unfiltered visibility into model outputs, reasoning traces, and error states is required for feedback collection and model improvement.
- **PTY Streaming**: Always preserve model reasoning and diagnostic sections (`Analysis & Strategy`, `Verification & Testing`, `Risks & Edge Cases`) in stdout and active `terminal-mcp` logs.

## 6. Codebase Navigation & Architecture Search (Graphify)
- **Graphify First**: For codebase structure, architecture questions, and symbol relationships, query Graphify before falling back to brute-force grep or directory scans.
  - **Queries**: Use `query_graph` via MCP (always passing `project_path`) or `graphify query "<question>"` via CLI.
  - **Tracing & Nodes**: Use `shortest_path` / `graphify path "<A>" "<B>"` for dependency chains and `get_node` for specific abstractions.
  - **Documentation**: Navigate `graphify-out/wiki/index.md` or `graphify-out/GRAPH_REPORT.md` instead of bulk reading raw source files.
  - **Graph Maintenance**: After modifying code files in a session, run `graphify update .` to keep the knowledge graph synchronized (AST-only, zero API cost).

## 7. Local Ollama MCP Server Protocol
- **Direct Native Tool Calling**: Always interact with Ollama, model lifecycle, and pipelines directly via native MCP tool calling (`call_mcp_tool` on the `local-ollama` server, e.g., `run_pipeline`, `ollama_list_models`, `ollama_chat`, `ollama_task_agent`).
- **No Script or Curl Bypasses**: Never bypass native MCP tool calling by running Python CLI scripts (`sysadmin/mcp_client.py`, `sysadmin/scripts/run_pipeline_mcp.py`), subshell wrappers, or raw `curl` commands against `http://127.0.0.1:11434`.
- **Halt on Tool Failure**: If any native MCP call fails or encounters an error, halt immediately and report the exact error and context. Do NOT attempt automated troubleshooting, diagnostic workarounds, or speculative fixes before discussing it with the user.

