# MCP CLI (`mcp_cli`)

A modular, extensible command-registry CLI package for orchestrating local Ollama multi-agent pipelines, inspecting systems, managing cognitive memory, and exporting fine-tuning datasets.

All subcommands are invocable via the top-level compatibility shim [`sysadmin/mcp_client.py`](../mcp_client.py) or as a module (`python3 -m mcp_cli`).

---

## 🏗️ Architecture & Registry

Subcommands are implemented as subclasses of `BaseCommand` and self-register via `@command`:

- **[`base.py`](base.py)**: Defines `BaseCommand` (with `register_args` and `run`) and the `@command` decorator.
- **[`cli.py`](cli.py)**: Dynamically builds the `argparse` parser from all registered commands.
- **[`commands/`](commands/)**: Domain-specific command implementations.

---

## 📦 Command Modules

| Domain | Module | Commands | Description |
|---|---|---|---|
| **Pipeline** | [`commands/pipeline.py`](commands/pipeline.py) | `pipeline-run`, `build-and-run` | Orchestrator ➔ Author ➔ Linter ➔ Reviewer multi-agent loops and single-shot execution with live reasoning streaming and trajectory logging. |
| **Datasets** | [`commands/dataset.py`](commands/dataset.py) | `export-dataset` | Export trajectory logs into fine-tuning datasets (DPO, SFT Multi-Turn, SFT Direct) with Chain-of-Thought (CoT) reasoning. |
| **Memory** | [`commands/memory.py`](commands/memory.py) | `memory-search`, `memory-list`, `memory-review`, `memory-compact`, etc. | Search, review, promote, and compact persistent cognitive memory lessons in `MemoryStore`. |
| **Hardware** | [`commands/verify_vram.py`](commands/verify_vram.py) | `verify-vram` | Verify host VRAM capacities against 8GB/16GB/24GB model tiers. |
| **Modelfiles** | [`commands/build_models.py`](commands/build_models.py) | `build-models` | Synthesize and register customized tiered Ollama Modelfiles (`winter-coder`, `winter-reviewer`, `winter-orchestrator`). |
| **Training** | [`commands/train.py`](commands/train.py) | `train` | Launch local fine-tuning workflows using exported datasets. |
| **Ollama** | [`commands/ollama.py`](commands/ollama.py) | `list-models`, `pull`, `chat`, `task`, `task-file`, `exec` | Query models, execute prompts, stream chat, and invoke model tools. |
| **Inspection** | [`commands/inspect.py`](commands/inspect.py) | `shellcheck`, `ansible-check` | Static analysis for Shell scripts and Ansible playbooks/tasks. |
| **Systemd** | [`commands/systemd.py`](commands/systemd.py) | `service-status`, `journal-logs` | Query systemctl service status and bounded journalctl logs. |
| **Files** | [`commands/files.py`](commands/files.py) | `write-file`, `read-file` | Workspace-constrained file reading, writing, and mode management. |
| **Terminal** | [`commands/terminal.py`](commands/terminal.py) | `type`, `view` | Send keystrokes and inspect screen buffers of active `terminal-mcp` PTY sessions. |

---

## 🚀 Usage & Examples

### 1. Execute Multi-Agent Pipeline (`pipeline-run`)

Runs the full Orchestrator ➔ Coder ➔ ShellCheck ➔ Reviewer loop with live terminal execution and automatic trajectory logging:

```bash
python3 sysadmin/mcp_client.py pipeline-run sysadmin/prompts/hello_world_test.md \
  --author winter-coder:8gb-trained \
  --reviewer qwen3:8b \
  --max-retries 3
```

### 2. Single-Turn Build & Run (`build-and-run`)

Generates code and native tool calls with full cognitive reasoning visible in `terminal-mcp`, executes live, and verifies outcome:

```bash
python3 sysadmin/mcp_client.py build-and-run sysadmin/prompts/hello_world_test.md \
  --model winter-coder:8gb-trained
```

### 3. Export Fine-Tuning Datasets (`export-dataset`)

Converts trajectory records into Chain-of-Thought (CoT) fine-tuning formats with role targeting and canonical taxonomy domain tagging:

```bash
# Export all formats (DPO, SFT direct, SFT multi-turn) with Coder CoT reasoning
python3 sysadmin/mcp_client.py export-dataset --output-dir sysadmin/data/training

# Export role-specific datasets (e.g. Orchestrator planning or Reviewer audits)
python3 sysadmin/mcp_client.py export-dataset --role orchestrator --format sft_direct
python3 sysadmin/mcp_client.py export-dataset --role reviewer --format sft_direct

# Export code-only without CoT reasoning prefixes
python3 sysadmin/mcp_client.py export-dataset --no-cot --format sft_direct
```

### 4. Search and Inspect Cognitive Memory

```bash
# Search memory for sandbox socket solutions
python3 sysadmin/mcp_client.py memory-search "sandbox socket seccomp"

# List lessons pending human review
python3 sysadmin/mcp_client.py memory-list --pending
```

### 5. Static Inspection & Syntax Checking

```bash
# Lint shell script with ShellCheck
python3 sysadmin/mcp_client.py shellcheck sysadmin/hello_world.sh

# Validate Ansible playbook syntax
python3 sysadmin/mcp_client.py ansible-check playbook.yml
```
