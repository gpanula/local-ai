# Linux SysAdmin & Ansible Engineering

This directory is dedicated to directing local AI agents to perform Linux systems administration, infrastructure coding, and autonomous multi-agent task execution.

## Topics & Artifacts
* Safe execution patterns (dry-runs, check-mode, idempotency verification)
* Custom Python Ansible modules (`AnsibleModule`, argument specs, test harnesses)
* Ansible playbooks, roles, and Jinja2 templates
* Diagnostic triage prompts and system troubleshooting workflows

---

## 🤖 MCP Tooling & Architecture

The sysadmin workspace includes a lightweight, modular Model Context Protocol (MCP) toolchain that connects local Ollama models with live terminal execution and verification gates:

* **[`mcp_cli/`](mcp_cli/README.md)**: Extensible command-registry CLI package providing structured subcommands for model queries, file operations, systemd log inspection, static analysis (ShellCheck / Ansible syntax check), and multi-agent synthesis loops. Subcommands are also invocable via [`mcp_client.py`](mcp_client.py).
* **[`mcp_core/`](mcp_core/README.md)**: Shared core library providing workspace path confinement (`validate_workspace_path`), JSON-RPC stdio transport (`call_mcp`), terminal streaming session management (`TerminalMCPSession`), and shell code sanitization (`sanitize_script_code`).
* **[`mcp_ollama/`](mcp_ollama/README.md)**: Zero-dependency stdio MCP server ([`server.py`](mcp_ollama/server.py)) exposing 11 tools for local model inference, task execution, syntax checking, and system inspection.
