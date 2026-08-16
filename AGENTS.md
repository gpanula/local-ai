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
