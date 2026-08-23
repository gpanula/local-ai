"""Optional live integration tests.

These require a running local Ollama instance and/or a live terminal-mcp socket.
Each test ``pytest.skip()`` (via ``skipif``) when the required service is
unavailable, so the suite stays green in offline environments.
"""

import os
import shutil
import urllib.request

import pytest

from mcp_core import transport
from mcp_core.workspace import is_valid_mcp_socket

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
TERMINAL_SOCKET = os.environ.get("TERMINAL_MCP_SOCKET", "/tmp/terminal-mcp.sock")


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _terminal_socket_available() -> bool:
    return is_valid_mcp_socket(TERMINAL_SOCKET)


def _terminal_mcp_binary_available() -> bool:
    return shutil.which("npx") is not None


@pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not reachable")
def test_list_models_roundtrip():
    out = transport.call_mcp("ollama_list_models", {})
    assert isinstance(out, str)
    assert out


@pytest.mark.skipif(
    not _terminal_socket_available() or not _terminal_mcp_binary_available(),
    reason="terminal-mcp not usable (missing socket or npx binary)",
)
def test_terminal_session_available():
    with transport.TerminalMCPSession() as session:
        assert session.is_available is True
