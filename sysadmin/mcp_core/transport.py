"""JSON-RPC transport to the Ollama MCP server and the terminal-mcp PTY.

Extracted from ``mcp_client.py``. ``TerminalMCPSession`` encapsulates the init +
``notifications/initialized`` handshake that was previously copy-pasted across
``send_terminal_mcp``, the ``type`` command, and the ``view`` command.
"""

import json
import logging
import os
import subprocess
import sys

from mcp_core.workspace import is_valid_mcp_socket

SERVER_PATH = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "mcp_ollama", "server.py")
)


def call_mcp(tool_name: str, arguments: dict) -> str:
    """Sends a JSON-RPC tools/call request to server.py and returns the output text."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }

    proc = subprocess.run(
        [sys.executable, SERVER_PATH],
        input=json.dumps(req) + "\n",
        capture_output=True,
        text=True
    )

    if proc.returncode != 0:
        raise RuntimeError(f"Server error (exit {proc.returncode}): {proc.stderr}")

    try:
        res = json.loads(proc.stdout.strip())
        if "error" in res:
            raise RuntimeError(f"JSON-RPC Error: {res['error']}\nServer stderr:\n{proc.stderr}")
        result = res.get("result", {})
        if result.get("isError"):
            raise RuntimeError(f"Tool Error: {result.get('content', [{}])[0].get('text')}\nServer stderr:\n{proc.stderr}")
        return result.get("content", [{}])[0].get("text", "")
    except json.JSONDecodeError:
        raise RuntimeError(f"Invalid JSON received from MCP server: {proc.stdout}\nServer stderr:\n{proc.stderr}")


class TerminalMCPSession:
    """Context manager for terminal-mcp JSON-RPC sessions.

    If no valid terminal-mcp socket is available, the session degrades to a
    safe no-op: ``type()``/``get_content()`` do nothing and ``is_available`` is
    ``False``.
    """

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, socket_path: str | None = None):
        self._socket_path = socket_path or os.environ.get("TERMINAL_MCP_SOCKET", "/tmp/terminal-mcp.sock")
        self._proc = None

    @property
    def is_available(self) -> bool:
        return getattr(self, "_sock", None) is not None or self._proc is not None

    def __enter__(self) -> "TerminalMCPSession":
        if not is_valid_mcp_socket(self._socket_path):
            return self
        import socket
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(self._socket_path)
            self._file = self._sock.makefile("r", encoding="utf-8")
        except (OSError, socket.error):
            self._sock = None
            self._file = None
        return self

    def __exit__(self, *exc) -> None:
        if getattr(self, "_file", None) is not None:
            try:
                self._file.close()
            except Exception:
                pass
        if getattr(self, "_sock", None) is not None:
            try:
                self._sock.close()
            except Exception:
                pass

    def type(self, text: str) -> None:
        if getattr(self, "_sock", None) is None:
            return
        payload = {"id": 1, "method": "type", "params": {"text": text.rstrip("\n") + "\n"}}
        self._sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        if self._file:
            self._file.readline()

    def get_content(self, visible_only: bool = False) -> str:
        if getattr(self, "_sock", None) is None:
            return ""
        payload = {"id": 2, "method": "getContent", "params": {"visibleOnly": visible_only}}
        self._sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        if self._file:
            line = self._file.readline()
            if line:
                res = json.loads(line)
                return res.get("result", {}).get("content", [{}])[0].get("text", "")
        return ""


def send_terminal_mcp(text: str) -> None:
    """Prints to local stdout and streams clean formatted comment banners directly into the active terminal-mcp PTY."""
    print(text)
    with TerminalMCPSession() as session:
        if not session.is_available:
            return
        clean_text = text.replace("\r", "")
        formatted_lines = []
        for line in clean_text.splitlines():
            stripped = line.strip()
            if not stripped:
                formatted_lines.append("")
            elif stripped.startswith("#"):
                formatted_lines.append(line)
            else:
                formatted_lines.append(f"# {line}")
        cmd = ("\n" if clean_text.startswith("\n") else "") + "\n".join(formatted_lines) + "\n"
        session.type(cmd)
