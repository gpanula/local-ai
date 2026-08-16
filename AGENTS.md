# Agent Workspace Rules

## 1. Git Commit Standards
* **Mandatory Gitmoji Prefix**: All Git commit messages created by the agent MUST start with a valid Gitmoji (Unicode emoji or shortcode) as defined in [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [gitmoji.dev](https://gitmoji.dev/).
* **Commit Message Format**: `<gitmoji> [optional scope]: <description>`
  * *Example*: `✨ (loom): add Ollama provider configuration`
  * *Example*: `📝 (roadmap): update MoE research goals`
  * *Example*: `🔧 (sysadmin): add check-mode dry-run verification`
* **Bot Author**: All commits must use the repository's local Git author configuration (`smurf-frank <frank@grumpy.smurf.work>`).

## 2. Safety & Verification Standards
* **Linux SysAdmin**: Always prefer dry-runs / check-mode / non-destructive inspection before applying changes.
* **Rollbacks & State**: Preserve file states and track changes cleanly.
