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
    parser.add_argument("--auditor-model", help="Secondary auditor model")
    parser.add_argument("--dual-model", action="store_true", help="Enable dual model residency (16gb + 8gb)")
    parser.add_argument("--dynamic-auditor", action="store_true", help="Enable dynamic dual mode auditor selection")
    parser.add_argument("--retry-budget", type=int, help="Maximum retry budget per task")
    parser.add_argument("--resume", help="Run ID to resume")
    args = parser.parse_args()

    tool_args = {"prompt": args.prompt, "model": args.model}
    if args.auditor_model:
        tool_args["auditor_model"] = args.auditor_model
    if args.dual_model:
        tool_args["dual_model"] = True
    if args.dynamic_auditor:
        tool_args["dynamic_auditor"] = True
    if args.retry_budget is not None:
        tool_args["retry_budget"] = args.retry_budget
    if args.resume:
        tool_args["resume"] = args.resume

    output = call_mcp("run_pipeline", tool_args)
    print(output)


if __name__ == "__main__":
    main()
