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
      "args": ["/home/pang/Projects/local-ai/sysadmin/mcp_ollama/server.py"],
      "env": {
        "OLLAMA_HOST": "http://127.0.0.1:11434"
      }
    }
  }
}
```
