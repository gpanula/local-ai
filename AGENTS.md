# Agent Workspace Rules

## 1. Branching & Workflow Standards
* **No Direct Commits to `main`**: Never commit directly to the `main` branch. All work must be conducted on dedicated feature or task branches.
* **Branch Naming Standard**:
  * `feat/<topic>` — New features, configurations, or modules (e.g., `feat/loom-ollama-routing`)
  * `fix/<topic>` — Bug fixes, syntax corrections, or troubleshooting (e.g., `fix/ansible-module-idempotency`)
  * `docs/<topic>` — Documentation, roadmaps, or notes (e.g., `docs/moe-benchmarks`)
  * `exp/<topic>` — Experiments, prototypes, or benchmarks (e.g., `exp/olmoe-throughput`)
* **Pull Request Workflow**: Push the branch and open/propose a Pull Request using the repository's PR template for human review and merge.

## 2. Git Commit Standards
* **Mandatory Gitmoji Prefix**: All Git commit messages created by the agent MUST start with a valid Gitmoji (Unicode emoji or shortcode) as defined in [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [gitmoji.dev](https://gitmoji.dev/).
* **Commit Message Format**: `<gitmoji> [optional scope]: <description>`
  * *Example*: `✨ (loom): add Ollama provider configuration`
  * *Example*: `📝 (roadmap): update MoE research goals`
  * *Example*: `🔧 (sysadmin): add check-mode dry-run verification`
* **Bot Author**: All commits must use the repository's local Git author configuration (`smurf-frank <frank@grumpy.smurf.work>`).

## 3. GitHub CLI & Credential Scoping (direnv)
* **Scoped Token Execution**: For all `gh` CLI operations (creating PRs, merging, querying PR status), the agent must utilize the repository-scoped environment provided by `direnv` (exporting `GH_TOKEN` from local `.git/credentials`).
* **Multi-User Isolation**: Never rely on or modify global `~/.config/gh/hosts.yml` defaults, preserving the human user's personal GitHub CLI sessions.

## 4. Safety & Verification Standards
* **Linux SysAdmin**: Always prefer dry-runs / check-mode / non-destructive inspection before applying changes.
* **Rollbacks & State**: Preserve file states and track changes cleanly.
* **Mandatory Terminal Buffer Inspection**: Antigravity must never rely solely on return codes (`exit 0`) or high-level status summaries from Ollama wrapper scripts. After any local AI execution pass, Antigravity MUST inspect the `terminal-mcp` buffer (via `getContent` or log inspection) to verify that the execution is genuinely free of runtime tracebacks, silent errors, or permission faults.
* **Defensive Scripting & Error Traps**: All shell scripts (authored by Antigravity or synthesized by Ollama) must implement strict defensive error handling:
  * Strict error headers: `set -euo pipefail`
  * Error trap diagnostics: `trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR`
  * Exit cleanup traps: `trap 'rm -rf "${TMP_DIR:-}"' EXIT`
  * Temporary Directory Resilience: Never assume `$TMPDIR` exists or is initialized. Always ensure parent directories exist (`mkdir -p "${TMPDIR:-/tmp}"`) or explicitly specify `-p /tmp` when creating scratch files/directories (e.g. `mktemp -d -p /tmp` or `mktemp -d "/tmp/script_XXXXXX"`).
  * Explicit binary assertions: Explicitly verify that required binaries exist and are executable (`[ -x "${BIN}" ]`) after build/install steps.
  * Explicit Virtual Environment & Binary Isolation: Sysadmin scripts must never rely on ambient system `$PATH` for project tooling. Scripts must deterministically resolve the target virtual environment (`VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"`) and invoke tools directly via explicit paths (`"${VENV_DIR}/bin/<binary>"`).
  * Functional sanity gates: Test binary execution and return codes before emitting success banners. Success banners (`🎉 ...`) must NEVER be printed if an intermediate assertion fails.

## 5. Privacy, Secrets & Sensitive Information
* **Zero Secret Commits**: Never commit, log, or hardcode API keys, personal access tokens (PATs), passwords, private SSH keys, or certificates. Always rely on environment variables (e.g., `$GH_TOKEN`, `$OLLAMA_HOST`) or git-ignored local credential files (`.git/credentials`).
* **Path & Identity Sanitization**: Never commit hardcoded user home directories (e.g., `/home/<user>`) or personally identifiable information into repository files. Always use `~`, `${HOME}`, or relative workspace paths.
* **Leak Prevention**: Ensure `.gitignore` continuously excludes `.env*`, credentials, local scratch logs, and environment configurations before staging changes.

## 6. Command Brevity & Permission Review Readability
* **Concise Shell Commands**: Avoid long, multi-line inline scripts (such as `python3 -c '...'` or embedded multi-line string blobs) in proposed tool commands to keep permission dialogs easy to review.
* **Script Encapsulation**: Encapsulate non-trivial Python or shell logic into dedicated scripts (e.g. in `sysadmin/` or CLI subcommands) and invoke them with short, clear command lines (e.g. `python3 sysadmin/mcp_client.py <subcommand> [args]`).

## 7. Zero-Polling & Live Terminal MCP Execution
* **Zero-Polling Policy**: Never poll in a tool-calling loop (`ollama ps`, status checks, sleep loops) while waiting for asynchronous commands, LLM inference, or background tasks to complete. Polling wastes API tokens and user budget.
* **Reactive Wakeup**: Launch asynchronous tasks once and yield immediately by stopping tool calls. Rely exclusively on the platform's reactive background notification to wake up upon completion.
* **Live Terminal MCP Visibility**: All interactive script creations, execution outputs, and live progress banners must be routed directly into the active `terminal-mcp` session so the developer can watch operations in real time without agent polling overhead.

## 8. Division of Agent Roles & Task Boundaries
* **Mandatory Human Review Gate for Prompts**: All prompt specification files (`sysadmin/prompts/*.md`) authored by Antigravity MUST be presented to and approved by the human developer before being submitted to or executed by the Local Ollama Agent.
* **Antigravity IDE (Orchestrator & Prompt Engineer)**:
  * **Role**: High-level task orchestration, prompt specification authoring, repository scaffolding, git lifecycle management, and architectural planning.
  * **Boundary**: Antigravity refines and maintains prompt specification files (`sysadmin/prompts/*.md`). Prompt specifications MUST define requirements, interface contracts, platform constraints, and defensive error-checking rules without spoon-feeding verbatim solution code to Ollama. Antigravity MUST NOT directly write or manually patch implementation scripts (e.g. `setup_ansible_env.sh`, `test_simple_venv.sh`) that are assigned to Ollama, and MUST request human review before delegating execution to the local AI.
* **Local Ollama Agent (Code Author & Live Executor)**:
  * **Role**: Autonomous script synthesis, command execution, and live terminal verification.
  * **Boundary**: Ollama reads approved task prompt specifications from `sysadmin/prompts/`, writes executable scripts via heredoc, executes them live in the active `terminal-mcp` session, and analyzes screen buffers to verify completion or diagnose runtime errors for prompt refinement.
