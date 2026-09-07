#!/usr/bin/env python3
"""Invokes the Arc-Orc-Rev multi-agent pipeline via the local-ollama MCP server."""

import argparse
import os
import sys

sysadmin_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
if sysadmin_dir not in sys.path:
    sys.path.insert(0, sysadmin_dir)

from mcp_core.transport import call_mcp


def main():
    parser = argparse.ArgumentParser(description="Invoke Arc-Orc-Rev pipeline through local-ollama MCP")
    parser.add_argument("prompt", help="Prompt text or path to markdown prompt file")
    parser.add_argument("--model", default="winter-prime:latest", help="Ollama model to use")
    parser.add_argument("--resume", help="Run ID to resume")
    args = parser.parse_args()

    tool_args = {"prompt": args.prompt, "model": args.model}
    if args.resume:
        tool_args["resume"] = args.resume

    output = call_mcp("run_pipeline", tool_args)
    print(output)


if __name__ == "__main__":
    main()
