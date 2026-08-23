"""Command-registry CLI package for the Local AI MCP tooling.

Replaces the monolithic ``mcp_client.py``. Subcommands are self-registering
``BaseCommand`` subclasses collected in ``mcp_cli.base.COMMAND_REGISTRY`` and
wired into an argparse dispatcher in ``mcp_cli.cli``.
"""
