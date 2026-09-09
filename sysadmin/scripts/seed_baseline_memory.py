#!/usr/bin/env python3
"""Seed baseline defensive bash and binary isolation lessons into .localai/memory.db."""

import os
import sys

# Ensure sysadmin is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp_core.memory import MemoryStore, DEFAULT_DB_PATH

BASELINE_LESSONS = [
    {
        "category": "Defensive Bash Scripting",
        "keywords": ["bash", "scripting", "trap", "err", "set -euo pipefail", "REPO_ROOT", "VENV_DIR", "binary assertions"],
        "rule": "Always enable `set -euo pipefail`, register an ERR trap (`trap 'echo \"❌ [ERROR] Script failed on line ${LINENO}\" >&2; exit 1' ERR`), deterministically resolve `REPO_ROOT` and `VENV_DIR`, and assert binary existence (`[ -x ... ]`) before emitting success.",
        "source_task": "sysadmin/prompts/hello_world_test.md",
        "lesson_type": "solved_pattern",
    },
    {
        "category": "Binary Isolation",
        "keywords": ["binary", "venv", "virtual environment", "binary isolation", "binary assertions", "deterministic resolution", "hardcoded paths"],
        "rule": "Never rely on ambient $PATH. Deterministically resolve virtual envs (`VENV_DIR=\"${1:-${REPO_ROOT}/sysadmin/venv}\"`) and invoke tools via explicit paths (`\"${VENV_DIR}/bin/<binary>\"`). Avoid hardcoding `/home/...` paths.",
        "source_task": "sysadmin/prompts/verify_code_quality_toolchain.md",
        "lesson_type": "solved_pattern",
    },
    {
        "category": "ShellCheck",
        "keywords": ["shellcheck", "sc2086", "sc2034", "quoting", "linters", "variable naming"],
        "rule": "Ensure all variables are double-quoted to prevent word splitting (SC2086), remove unreferenced variables (SC2034), and pass pre-flight ShellCheck verification.",
        "source_task": "sysadmin/prompts/verify_code_quality_toolchain.md",
        "lesson_type": "solved_pattern",
    },
]


def main():
    os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)
    with MemoryStore(DEFAULT_DB_PATH) as store:
        existing = store.list_lessons()
        existing_rules = {l["rule"] for l in existing}
        inserted = 0
        for item in BASELINE_LESSONS:
            if item["rule"] not in existing_rules:
                lid = store.insert_lesson(item)
                print(f"✅ Seeded lesson {lid}: {item['category']}")
                inserted += 1
            else:
                print(f"ℹ️ Lesson already present: {item['category']}")

        total = len(store.list_lessons())
        print(f"🎉 Baseline memory seeding complete. Active lessons in DB: {total}")


if __name__ == "__main__":
    main()
