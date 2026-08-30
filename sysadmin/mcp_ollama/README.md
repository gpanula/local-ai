# Local Ollama Model Context Protocol (MCP) Server

A lightweight, zero-dependency JSON-RPC 2.0 stdio MCP server bridging AI orchestrators and IDE clients directly to local Ollama instances (`http://127.0.0.1:11434`) and Linux systems administration capabilities.

---

## 🛠️ Exposed Tools

1. **`write_file`**:
   * Writes or appends text content to a local file within the workspace with optional executable permissions (`chmod +x`).
2. **`read_file`**:
   * Reads text content from a local file within the workspace with optional line range slicing (`start_line`, `end_line`) and byte bounding.
3. **`ollama_list_models`**:
   * Lists all local models with disk size, parameter counts, architecture family, and quantization levels.
4. **`ollama_chat`**:
   * Sends multi-turn chat prompts to any local model (`qwen3:8b`, `mistral-nemo:12b`, `qwen2.5-coder:7b`, etc.).
   * Supports `system_prompt`, `temperature`, and context window adjustments (`num_ctx`).
5. **`ollama_task_agent`**:
   * Autonomous task solver that executes a structured Analysis ➔ Implementation ➔ Verification ➔ Risk Analysis pipeline on Ollama.
6. **`ollama_pull_model`**:
   * Pulls new models from Ollama's registry into the local GPU environment.
7. **`ollama_execute_task`**:
   * Executes commands in the live `terminal-mcp` PTY socket and passes output to Ollama for verification.
8. **`ansible_syntax_check`**:
   * Validates Ansible playbook or task YAML syntax using an isolated concurrency-safe temporary environment.
9. **`shellcheck_inspect`**:
   * Runs ShellCheck static analysis on bash/sh scripts to identify syntax issues, quoting bugs, and trap errors.
10. **`service_status`**:
    * Queries systemctl service status with bounded unpaged output.
11. **`journal_logs`**:
    * Queries bounded journalctl log entries filtered by unit, priority, time window, and lines limit.

---

## 🚀 Multi-Agent Pipeline Execution

The CLI package ([`sysadmin/mcp_cli/commands/pipeline.py`](../mcp_cli/commands/pipeline.py)) includes a `pipeline-run` orchestration loop that coordinates multiple tools for safe execution:
1. **Authoring**: Synthesizes a script to achieve a prompt's goals using a coder model (e.g. `qwen2.5-coder:7b`).
2. **Pre-flight Linting**: Validates the authored script via `shellcheck_inspect`.
3. **Verification**: Submits the script, linter output, and execution context to a strict Reviewer model (e.g. `qwen3:8b`) for approval.
4. **Live Execution**: Executes the verified script in the `terminal-mcp` interactive PTY for live observability.

Run the pipeline via:
```bash
python3 sysadmin/mcp_client.py pipeline-run sysadmin/prompts/<prompt_file>.md
```

> 📋 **Tooling Roadmap & Rollout Plan**: See [TOOLS_ROADMAP.md](./TOOLS_ROADMAP.md) for the upcoming tool additions (pre-flight linters, sysadmin inspection, GPU telemetry, and state management).

---

## 🧪 Testing

Run the MCP server unit tests:
```bash
python3 -m unittest sysadmin/mcp_ollama/test_server.py
```

Run the full pytest suite for MCP tooling:
```bash
pytest sysadmin/tests/
```

---

## ⚙️ MCP Registration

In `~/.gemini/config/mcp_config.json` or your MCP client configuration:
```json
{
  "mcpServers": {
    "local-ollama": {
      "command": "python3",
      "args": ["/absolute/path/to/local-ai_vscodium/sysadmin/mcp_ollama/server.py"],
      "env": {
        "OLLAMA_HOST": "http://127.0.0.1:11434"
      }
    }
  }
}
```
