"""Shared pytest fixtures for the mcp_cli / mcp_core test suite.

Adds ``sysadmin/`` to ``sys.path`` so ``mcp_core`` and ``mcp_cli`` are
importable regardless of the directory pytest is invoked from.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from mcp_core import transport  # noqa: E402


@pytest.fixture
def fake_call_mcp(monkeypatch):
    """Monkeypatch ``mcp_core.transport.call_mcp``; records calls and returns canned text."""
    calls = []

    def _fake(tool_name, arguments):
        calls.append((tool_name, arguments))
        return "mocked"

    monkeypatch.setattr(transport, "call_mcp", _fake)
    return calls


class _FakeTerminalSession:
    """In-memory stand-in for ``mcp_core.transport.TerminalMCPSession``."""

    is_available = True

    def __init__(self, socket_path=None):
        self.typed = []
        self.content = "fake terminal viewport"
        self.visible_only = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def type(self, text):
        self.typed.append(text)

    def get_content(self, visible_only=False):
        self.visible_only = visible_only
        return self.content


@pytest.fixture
def fake_terminal_session(monkeypatch):
    """Monkeypatch ``mcp_core.transport.TerminalMCPSession`` with an in-memory fake."""
    monkeypatch.setattr(transport, "TerminalMCPSession", _FakeTerminalSession)
    return _FakeTerminalSession


@pytest.fixture
def fake_send_terminal_mcp(monkeypatch):
    """Monkeypatch ``mcp_core.transport.send_terminal_mcp`` to record banner messages."""
    sent = []
    monkeypatch.setattr(transport, "send_terminal_mcp", sent.append)
    return sent
