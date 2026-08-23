#!/usr/bin/env python3
"""Lightweight CLI Client for Local Ollama MCP Server.

Thin shim over the ``mcp_cli`` command-registry package. Preserves the
historical ``python3 sysadmin/mcp_client.py <subcommand>`` entry point.
"""

import os
import sys

# Ensure `mcp_cli` / `mcp_core` (siblings in sysadmin/) are importable no matter
# which directory the shim is invoked from.
sys.path.insert(0, os.path.realpath(os.path.dirname(__file__)))

from mcp_cli.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
