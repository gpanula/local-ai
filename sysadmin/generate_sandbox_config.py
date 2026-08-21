#!/usr/bin/env python3
"""
Dynamic Sandbox Configuration Generator for Terminal MCP.
Resolves workspace paths, expands symlinks, and generates a validated
runtime sandbox configuration without hardcoding machine-specific paths.
"""

import argparse
import json
import os
import sys
from pathlib import Path


def generate_config(template_path: str, output_path: str, workspace_paths: list[str]) -> str:
    template_file = Path(template_path).resolve()
    if not template_file.is_file():
        raise FileNotFoundError(f"Template config not found: {template_path}")

    with open(template_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    read_write = config.get("filesystem", {}).get("readWrite", [])
    read_only = config.get("filesystem", {}).get("readOnly", [])

    resolved_rw = []
    seen = set()

    def add_path(target_path: str, target_list: list[str]):
        expanded = os.path.expanduser(target_path)
        real = os.path.realpath(expanded)
        for p in [expanded, real]:
            if p and p not in seen:
                seen.add(p)
                target_list.append(p)

    # Add dynamic workspace paths first
    for wp in workspace_paths:
        if not wp:
            continue
        add_path(wp, resolved_rw)

    # Add remaining template readWrite entries (excluding placeholders or hardcoded ~/Projects/local-ai)
    for entry in read_write:
        if entry in ("~/Projects/local-ai", "${WORKSPACE}", "{{WORKSPACE}}"):
            continue
        add_path(entry, resolved_rw)

    # Resolve readOnly paths (preserving ~ expansion)
    resolved_ro = []
    seen_ro = set()
    for entry in read_only:
        expanded = os.path.expanduser(entry)
        if expanded not in seen_ro:
            seen_ro.add(expanded)
            resolved_ro.append(expanded)

    config.setdefault("filesystem", {})
    config["filesystem"]["readWrite"] = resolved_rw
    config["filesystem"]["readOnly"] = resolved_ro

    output_file = Path(output_path).resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write runtime config with restrictive permissions (0600)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    os.chmod(output_file, 0o600)

    return str(output_file)


def main():
    parser = argparse.ArgumentParser(description="Generate dynamic sandbox config for terminal-mcp")
    parser.add_argument("--template", required=True, help="Path to base sandbox config template")
    parser.add_argument("--output", required=True, help="Path for generated runtime sandbox config")
    parser.add_argument("--workspace", action="append", default=[], help="Workspace directory path(s)")

    args = parser.parse_args()

    try:
        out_path = generate_config(args.template, args.output, args.workspace)
        print(out_path)
    except Exception as e:
        print(f"❌ [ERROR] Failed to generate sandbox config: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
