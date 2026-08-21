# Local Ollama Model Context Protocol (MCP) Server

A lightweight, zero-dependency JSON-RPC 2.0 stdio MCP server bridging AI orchestrators and Antigravity IDE directly to local Ollama instances (`http://127.0.0.1:11434`).

---

## 🛠️ Exposed Tools

1. **`ollama_list_models`**:
   * Lists all local models with disk size, parameter counts, architecture family, and quantization levels.
2. **`ollama_chat`**:
   * Sends multi-turn chat prompts to any local model (`qwen3:8b`, `mistral-nemo:12b`, `qwen2.5-coder:7b`, etc.).
   * Supports `system_prompt`, `temperature`, and context window adjustments (`num_ctx`).
3. **`ollama_task_agent`**:
   * Autonomous task solver that executes a structured Analysis ➔ Implementation ➔ Verification ➔ Risk Analysis pipeline on Ollama.
4. **`ollama_pull_model`**:
   * Pulls new models from Ollama's registry into the local GPU environment.
5. **`ollama_execute_task`**:
   * Executes commands in the live terminal-mcp PTY socket and passes output to Ollama for verification.
6. **`ansible_syntax_check`**:
   * Validates Ansible playbook or task YAML syntax using an isolated concurrency-safe temporary environment.
7. **`shellcheck_inspect`**:
   * Runs ShellCheck static analysis on bash/sh scripts.
8. **`service_status`**:
   * Queries systemctl service status with bounded unpaged output.
9. **`journal_logs`**:
   * Queries bounded journalctl log entries filtered by unit, priority, and lines limit.

## 🚀 Multi-Agent Pipeline Execution

The `mcp_client.py` includes a `pipeline-run` orchestration loop that coordinates multiple tools for safe execution:
1. **Authoring**: Synthesizes a script to achieve a prompt's goals using a coder model.
2. **Pre-flight Linting**: Validates the authored script (e.g. via `shellcheck_inspect`).
3. **Verification**: Submits the script, linter output, and execution context to a strict Reviewer model for approval.
4. **Live Execution**: Executes the verified script in the `terminal-mcp` interactive PTY for live observability.

> 📋 **Tooling Roadmap & Rollout Plan**: See [TOOLS_ROADMAP.md](./TOOLS_ROADMAP.md) for the upcoming tool additions (pre-flight linters, sysadmin inspection, GPU telemetry, and state management).

---

## 🧪 Testing

Run the test suite:
```bash
python3 -m unittest sysadmin/mcp_ollama/test_server.py
```

---

## ⚙️ Antigravity Registration

In `~/.gemini/config/mcp_config.json`:
```json
{
  "mcpServers": {
    "local-ollama": {
      "command": "python3",
      "args": ["~/Projects/local-ai/sysadmin/mcp_ollama/server.py"],
      "env": {
        "OLLAMA_HOST": "http://127.0.0.1:11434"
      }
    }
  }
}
```
