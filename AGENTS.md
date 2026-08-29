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

## 3. Security & Cleanliness
- **Secrets**: Never commit/log keys, tokens, passwords. Use `$GH_TOKEN`, `$OLLAMA_HOST`, or git-ignored files.
- **Sanitization**: No hardcoded `/home/<user>`. Use `~`, `$HOME`, or relative workspace paths.
- **Readability**: Avoid multi-line `python -c` in tool calls. Wrap logic in `sysadmin/*.py` scripts.

## 4. Execution & Boundaries
- **No Polling**: No `sleep`/`ollama ps` polling loops. Launch async tasks, yield tool calls, wait for reactive notifications.
- **Terminal Routing**: Output live progress to active `terminal-mcp` session.
- **Human Gate**: Antigravity writes prompt specs (`sysadmin/prompts/*.md`); human must approve before delegating to Ollama.
- **Role Split**:
  - *Antigravity*: Orchestration, architecture, specs, git lifecycle. DO NOT write/patch Ollama implementation scripts directly.
  - *Ollama*: Script synthesis via heredoc, execution, buffer analysis.