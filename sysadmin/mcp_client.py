#!/usr/bin/env python3
"""Lightweight CLI Client for Local Ollama MCP Server.

Thin shim over the ``mcp_cli`` command-registry package. Preserves the
historical ``python3 sysadmin/mcp_client.py <subcommand>`` entry point.
"""

import os
import sys

# Deterministic Virtual Environment Isolation (Rule 2 AGENTS.md)
# If invoked from ambient system Python, re-exec using sysadmin/venv/bin/python3.
_this_dir = os.path.realpath(os.path.dirname(__file__))
_venv_python = os.path.join(_this_dir, "venv", "bin", "python3")
if os.path.isfile(_venv_python) and os.path.realpath(sys.executable) != os.path.realpath(_venv_python):
    os.execv(_venv_python, [_venv_python] + sys.argv)

# Ensure `mcp_cli` / `mcp_core` (siblings in sysadmin/) are importable no matter
# which directory the shim is invoked from.
sys.path.insert(0, _this_dir)

from mcp_cli.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
