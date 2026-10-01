# Local Ollama Model Context Protocol (MCP) Server

A lightweight, zero-dependency JSON-RPC 2.0 stdio MCP server bridging AI orchestrators, IDE clients, and local Ollama instances (`http://127.0.0.1:11434`) with live terminal execution and Linux systems administration capabilities.

---

## 🛠️ Exposed Tools

1. **`write_file`**:
   * Writes or appends text content to a local file within the workspace with optional executable permissions (`chmod +x`).
2. **`read_file`**:
   * Reads text content from a local file within the workspace with optional line range slicing (`start_line`, `end_line`) and byte bounding (`max_bytes`).
3. **`ollama_list_models`**:
   * Lists all local models with disk size, parameter counts, architecture family, and quantization levels.
4. **`ollama_chat`**:
   * Sends chat prompts or multi-turn messages to any local model (`winter-coder:8gb-trained`, `qwen3:8b`, `qwen2.5-coder:7b`, etc.).
   * Supports `prompt`, `messages`, `system_prompt`, `temperature`, `top_p`, and context window adjustments (`num_ctx`).
5. **`ollama_task_agent`**:
   * Autonomous task solver that executes a structured Analysis ➔ Implementation ➔ Verification ➔ Risk Analysis cognitive workflow. Supports toggling native tool calls via `enable_tools` (`write_file`, `read_file`).
6. **`ollama_pull_model`**:
   * Pulls new models from Ollama's registry into the local GPU environment.
7. **`ollama_unload_model`**:
   * Evicts loaded models from VRAM to release memory for subsequent pipeline phases or large models.
8. **`ollama_execute_task`**:
   * Executes commands in the live `terminal-mcp` PTY via direct Unix domain socket communication (`/tmp/terminal-mcp.sock`) with automatic fallback to host subprocess execution. Analyzes and verifies the terminal outcome via an Ollama reviewer model with bounded timeout (`timeout`, default 180s).
9. **`ansible_syntax_check`**:
   * Validates Ansible playbook or task YAML syntax using an isolated concurrency-safe temporary environment.
10. **`shellcheck_inspect`**:
    * Runs ShellCheck static analysis on bash/sh scripts to identify syntax issues, quoting bugs, and trap errors.
11. **`service_status`**:
    * Queries systemctl service status with bounded unpaged output (`unit`, `failed_only`).
12. **`journal_logs`**:
    * Queries bounded journalctl log entries filtered by unit, priority, time window (`since`), and lines limit.
13. **`run_pipeline`** (alias: **`process_prompt`**):
    * Directly executes the Arc-Orc-Rev multi-agent pipeline (Architect ➔ Orchestrator ➔ Reviewer Gate ➔ Security Gate ➔ Pre-Execution Code Gates ➔ Live Execution ➔ Memory Attribution & Trajectory Persistence) on a task prompt or prompt file.
    * Configurable parameters: `prompt`, `model`, `auditor_model`, `dual_model`, `dynamic_auditor`, `retry_budget`, and `resume`.

---

## ⚙️ MCP Registration & Environment Isolation

> [!IMPORTANT]
> **Virtual Environment Python Mandatory**: The `local-ollama` MCP server orchestrates the full `pipeline.py` workflow, state persistence, AST parsing, and trajectory compression. These features require dependencies installed in `${REPO_ROOT}/sysadmin/venv` (such as `zstandard`, `yaml`, `pytest`, `ansible-lint`, etc.).
> 
> Running the MCP server with the system `/usr/bin/python3` or an ambient `$PATH` interpreter will cause `ModuleNotFoundError` (e.g. `No module named 'zstandard'`). Always configure `mcp_config.json` with the explicit virtual environment Python binary.

To expose the `local-ollama` tools directly to IDE clients (e.g. Antigravity / Gemini Code Assist) without permission prompts, register the server in `~/.gemini/antigravity-ide/mcp_config.json` or `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "local-ollama": {
      "command": "/mypool/valkyrie/home/pang/Projects/local-ai/sysadmin/venv/bin/python3",
      "args": [
        "/mypool/valkyrie/home/pang/Projects/local-ai/sysadmin/mcp_ollama/server.py"
      ],
      "env": {
        "OLLAMA_HOST": "http://127.0.0.1:11434",
        "TERMINAL_MCP_SOCKET": "/tmp/terminal-mcp.sock"
      }
    }
  }
}
```

---

## 🧪 Testing

Run all unit tests using the project's isolated virtual environment:

```bash
sysadmin/venv/bin/pytest sysadmin/tests/
```
