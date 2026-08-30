# MCP Core Library (`mcp_core`)

A shared core library providing foundational utilities for workspace path confinement, JSON-RPC communication with the local Ollama MCP server, `terminal-mcp` session management, and script sanitization.

Consumed by both the command-line interface ([`sysadmin/mcp_cli`](sysadmin/mcp_cli/README.md)) and the local server backend ([`sysadmin/mcp_ollama/server.py`](sysadmin/mcp_ollama/server.py)).

---

## 🧩 Core Modules

### 1. Workspace Confinement (`workspace.py`)
- **[`sysadmin/mcp_core/workspace.py`](sysadmin/mcp_core/workspace.py)**:
  - `WORKSPACE_ROOT`: Dynamically resolved repository root path.
  - `validate_workspace_path(path: str, purpose: str = "file") -> str`: Resolves absolute/relative paths and asserts that target paths strictly reside within `WORKSPACE_ROOT` to prevent path traversal attacks.
  - `is_valid_mcp_socket(path: str) -> bool`: Verifies that a Unix domain socket path exists, is a valid socket, is not a symlink, and is owned by the current user UID.

### 2. Transport & Terminal Session (`transport.py`)
- **[`sysadmin/mcp_core/transport.py`](sysadmin/mcp_core/transport.py)**:
  - `call_mcp(tool_name: str, arguments: dict) -> str`: Executes a JSON-RPC 2.0 `tools/call` invocation against [`sysadmin/mcp_ollama/server.py`](sysadmin/mcp_ollama/server.py) over stdio and extracts text responses or raises descriptive runtime errors.
  - `TerminalMCPSession`: Context manager handling the initialization handshake (`initialize` and `notifications/initialized`) with `terminal-mcp`. Degrades safely to a no-op if the socket or binary is unavailable.
  - `send_terminal_mcp(text: str) -> None`: Formats and streams comment-prefixed status updates and banners to both local stdout and the live interactive `terminal-mcp` PTY window.

### 3. Script Sanitization (`sanitize.py`)
- **[`sysadmin/mcp_core/sanitize.py`](sysadmin/mcp_core/sanitize.py)**:
  - `sanitize_script_code(code: str) -> str`: Normalizes extracted code snippets by stripping common leading indentation (dedenting) and ensuring shell heredoc closing delimiters (e.g. `EOF`, `EOT`, `ENDOFFILE`) are unindented on column 0.

---

## 🚀 Usage & Examples

### Invoking MCP Server Tools Programmatically

```python
from mcp_core.transport import call_mcp

# List installed Ollama models
models_info = call_mcp("ollama_list_models", {})
print(models_info)

# Execute ShellCheck static analysis
lint_result = call_mcp("shellcheck_inspect", {
    "script": "echo 'Hello World'"
})
print(lint_result)
```

### Path Validation

```python
from mcp_core.workspace import validate_workspace_path

# Safe resolution of relative workspace path
safe_path = validate_workspace_path("sysadmin/hello_world.sh", purpose="script")

# Raises ValueError if path attempts directory traversal outside repository root
try:
    bad_path = validate_workspace_path("/etc/shadow")
except ValueError as e:
    print(f"Trapped unsafe path: {e}")
```

### Terminal MCP Session

```python
from mcp_core.transport import TerminalMCPSession, send_terminal_mcp

# Send formatted banner to terminal
send_terminal_mcp("🤖 [Agent] Starting automated build task...")

# Interactive keystroke injection and buffer read
with TerminalMCPSession() as session:
    if session.is_available:
        session.type("ls -la\n")
        buffer_text = session.get_content(visible_only=True)
        print("Live Terminal Buffer:\n", buffer_text)
```
