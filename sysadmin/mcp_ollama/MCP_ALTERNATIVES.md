# Alternative MCP Servers for Ollama & Local AI

This document catalogs existing open-source Model Context Protocol (MCP) servers that can interface with local Ollama instances or serve as alternative task execution harnesses.

---

## 1. 🌟 Loom Native MCP Server (`sfw/loom`)
* **Repository**: [sfw/loom on GitHub](https://github.com/sfw/loom)
* **Transport**: Python / `uv`
* **Command**:
  ```bash
  uv run loom mcp-serve
  ```
* **Overview & Strengths**:
  * Exposes Loom’s entire **agentic execution harness** (task decomposition, dependency graphs, fuzzy file editing, snapshot rollbacks, and independent verifiers) directly as an MCP tool provider.
  * Designed specifically for complex, multi-step coding, sysadmin, and research workflows with local and hybrid LLMs.
* **Antigravity Config (`mcp_config.json`)**:
  ```json
  "loom-harness": {
    "command": "uv",
    "args": ["run", "--directory", "/home/pang/Projects/local-ai/loom/loom-repo", "loom", "mcp-serve"]
  }
  ```

---

## 2. 📦 LobeHub Ollama MCP (`@lobehub/ollama-mcp`)
* **Repository**: [LobeHub Ollama MCP on GitHub](https://github.com/Dxeo/ollama-mcp) / [npm package](https://www.npmjs.com/package/@lobehub/ollama-mcp)
* **Transport**: Node.js / `npx`
* **Command**:
  ```bash
  npx -y @lobehub/ollama-mcp
  ```
* **Overview & Strengths**:
  * Fast, zero-install execution via `npx`.
  * Exposes chat completion, semantic search / embeddings, and model management tools to any MCP client.
* **Antigravity Config (`mcp_config.json`)**:
  ```json
  "lobe-ollama": {
    "command": "npx",
    "args": ["-y", "@lobehub/ollama-mcp"],
    "env": {
      "OLLAMA_HOST": "http://127.0.0.1:11434"
    }
  }
  ```

---

## 3. 🐍 Rawveg Ollama MCP (`rawveg/ollama-mcp`)
* **Repository**: [rawveg/ollama-mcp on GitHub](https://github.com/rawveg/ollama-mcp)
* **Transport**: Python / `uvx`
* **Command**:
  ```bash
  uvx ollama-mcp
  ```
* **Overview & Strengths**:
  * Direct Python wrapper around the official `ollama-python` library.
  * Lightweight and standard-compliant for environments using `uv`.
* **Antigravity Config (`mcp_config.json`)**:
  ```json
  "rawveg-ollama": {
    "command": "uvx",
    "args": ["ollama-mcp"],
    "env": {
      "OLLAMA_HOST": "http://127.0.0.1:11434"
    }
  }
  ```
