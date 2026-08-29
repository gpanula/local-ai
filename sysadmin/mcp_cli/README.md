# MCP CLI (`mcp_cli`)

A modular, extensible command-registry CLI package for interacting with local Ollama instances and the Model Context Protocol (MCP) server.

Replaces the monolithic `mcp_client.py` with self-registering command modules while preserving backwards compatibility via a thin `mcp_client.py` entry point shim.

---

## 🏗️ Architecture & Registry

Subcommands are implemented as subclasses of `BaseCommand` and decorated with `@command`:

- **[`sysadmin/mcp_cli/base.py`](sysadmin/mcp_cli/base.py)**: Defines `BaseCommand` (with `register_args` and `run` abstract methods) and the `@command` decorator which populates `COMMAND_REGISTRY`.
- **[`sysadmin/mcp_cli/cli.py`](sysadmin/mcp_cli/cli.py)**: Builds the `argparse` parser dynamically from all registered commands and dispatches execution.
- **[`sysadmin/mcp_cli/__main__.py`](sysadmin/mcp_cli/__main__.py)**: Provides executable module support (`python3 -m mcp_cli`).
- **[`sysadmin/mcp_cli/commands/`](sysadmin/mcp_cli/commands/)**: Contains isolated subcommand modules organized by functional domain.

---

## 📦 Command Modules

| Category | Module | Commands | Description |
|---|---|---|---|
| **Ollama** | [`commands/ollama.py`](sysadmin/mcp_cli/commands/ollama.py) | `list-models`, `pull`, `chat`, `task`, `task-file`, `exec` | Query models, execute single-shot or file prompts, run chat sessions, and execute verified tasks. |
| **Pipeline** | [`commands/pipeline.py`](sysadmin/mcp_cli/commands/pipeline.py) | `pipeline-run`, `build-and-run` | Multi-agent synthesis & review loops (`Author -> Lint -> Review -> Live Execution`). |
| **Inspection** | [`commands/inspect.py`](sysadmin/mcp_cli/commands/inspect.py) | `shellcheck`, `ansible-check` | Static analysis and syntax validation for Shell scripts and Ansible playbooks/tasks. |
| **Systemd** | [`commands/systemd.py`](sysadmin/mcp_cli/commands/systemd.py) | `service-status`, `journal-logs` | Query systemctl service status and retrieve bounded journalctl log entries. |
| **Files** | [`commands/files.py`](sysadmin/mcp_cli/commands/files.py) | `write-file`, `read-file` | Workspace-constrained file reading, writing, and appending with permission management. |
| **Terminal** | [`commands/terminal.py`](sysadmin/mcp_cli/commands/terminal.py) | `type`, `view` | Send keystrokes and inspect screen buffers of active `terminal-mcp` PTY sessions. |

---

## 🚀 Usage & Examples

### Invocation Entry Points

You can invoke commands either via the top-level compatibility shim:
```bash
python3 sysadmin/mcp_client.py <command> [options]
```
or as a Python module (with `sysadmin` on `PYTHONPATH` or executed from `sysadmin/`):
```bash
python3 -m mcp_cli <command> [options]
```

### Examples

#### 1. List Local Models & Run Chat
```bash
python3 sysadmin/mcp_client.py list-models
python3 sysadmin/mcp_client.py chat "Explain systemd cgroups v2" --model qwen3:8b
```

#### 2. Multi-Agent Authoring & Review Pipeline
```bash
# Run multi-agent pipeline with ShellCheck linting and strict verification review
python3 sysadmin/mcp_client.py pipeline-run sysadmin/prompts/simple_venv.md \
  --author qwen2.5-coder:7b \
  --reviewer qwen3:8b \
  --max-retries 3

# Dry-run mode (stops after review approval without executing)
python3 sysadmin/mcp_client.py pipeline-run sysadmin/prompts/simple_venv.md --dry-run
```

#### 3. Static Inspection & Syntax Checking
```bash
# Lint shell script with ShellCheck
python3 sysadmin/mcp_client.py shellcheck sysadmin/hello_world.sh

# Validate Ansible playbook syntax
python3 sysadmin/mcp_client.py ansible-check playbook.yml
```

#### 4. File Operations & Systemd Inspection
```bash
# Write executable script into workspace
python3 sysadmin/mcp_client.py write-file sysadmin/test.sh "echo hello" --exec

# Inspect systemd unit logs
python3 sysadmin/mcp_client.py service-status systemd-journald
python3 sysadmin/mcp_client.py journal-logs systemd-journald --lines 20 --priority err
```
