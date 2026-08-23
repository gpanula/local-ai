"""Argparse dispatcher that wires up the command registry."""

import argparse
import logging

import mcp_cli.commands  # noqa: F401 — triggers registration
from mcp_cli.base import COMMAND_REGISTRY


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level parser and one subparser per registered command."""
    parser = argparse.ArgumentParser(description="Ollama MCP Client CLI")
    subs = parser.add_subparsers(dest="command", required=True)
    for name, cmd in COMMAND_REGISTRY.items():
        sub = subs.add_parser(name, help=cmd.help)
        cmd.register_args(sub)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    COMMAND_REGISTRY[args.command].run(args)
