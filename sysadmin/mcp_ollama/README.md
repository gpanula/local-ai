# Local Ollama Model Context Protocol (MCP) Server

A lightweight, zero-dependency JSON-RPC 2.0 stdio MCP server bridging AI orchestrators, IDE clients, and local Ollama instances (`http://127.0.0.1:11434`) with live terminal execution and Linux systems administration capabilities.

---

## 🛠️ Exposed Tools

1. **`write_file`**:
   * Writes or appends text content to a local file within the workspace with optional executable permissions (`chmod +x`).
2. **`read_file`**:
   * Reads text content from a local file within the workspace with optional line range slicing (`start_line`, `end_line`) and byte bounding.
3. **`ollama_list_models`**:
   * Lists all local models with disk size, parameter counts, architecture family, and quantization levels.
4. **`ollama_chat`**:
   * Sends multi-turn chat prompts to any local model (`winter-coder:8gb-trained`, `qwen3:8b`, `qwen2.5-coder:7b`, etc.).
   * Supports `system_prompt`, `temperature`, and context window adjustments (`num_ctx`).
5. **`ollama_task_agent`**:
   * Autonomous task solver that executes a structured Analysis ➔ Implementation ➔ Verification ➔ Risk Analysis cognitive workflow. Supports emitting native tool calls (`write_file`, `read_file`).
6. **`ollama_pull_model`**:
   * Pulls new models from Ollama's registry into the local GPU environment.
7. **`ollama_unload_model`**:
   * Evicts loaded models from VRAM to release memory for subsequent pipeline phases or large models.
8. **`ollama_execute_task`**:
   * Executes commands in the live `terminal-mcp` PTY via direct Unix domain socket communication (`/tmp/terminal-mcp.sock`) with automatic fallback to host subprocess execution. Analyzes and verifies the terminal outcome via an Ollama reviewer model.
9. **`ansible_syntax_check`**:
   * Validates Ansible playbook or task YAML syntax using an isolated concurrency-safe temporary environment.
10. **`shellcheck_inspect`**:
    * Runs ShellCheck static analysis on bash/sh scripts to identify syntax issues, quoting bugs, and trap errors.
11. **`service_status`**:
    * Queries systemctl service status with bounded unpaged output.
12. **`journal_logs`**:
    * Queries bounded journalctl log entries filtered by unit, priority, time window, and lines limit.

---

## ⚙️ MCP Registration

To expose the `local-ollama` tools directly to IDE clients (e.g. Antigravity / Gemini Code Assist) without permission prompts, register the server in `~/.gemini/config/mcp_config.json`:

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
