# Proven Lesson: Negative Assertion Logic in Defensive Bash

---
id: lesson-20260930-01
category: Defensive Bash Scripting
keywords: [bash, negative assertions, error handling, syntax testing, exit codes, set -e, failure detection, python ast, yaml, shellcheck, ansible]
created: 2026-09-30
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
lesson_type: proven_pattern
---

**Rule**: When testing negative assertions in defensive Bash scripts (verifying that invalid syntax, malformed configurations, or flawed scripts fail parsing as expected), NEVER write `if ! command; then echo "Validation failed"; exit 1; fi` — the exclamation mark inverts the command's expected non-zero error exit into success (0), causing the error branch to trigger and abort the script! Instead, directly test the command without negation and abort only if the command unexpectedly succeeds:
```bash
# Correct negative assertion pattern:
if "${VENV_DIR}/bin/python" -c "import ast; ast.parse('invalid syntax')" >/dev/null 2>&1; then
    echo "❌ Failed to catch syntax error"
    exit 1
fi
```
Always redirect both stdout and stderr (`>/dev/null 2>&1`) so that expected syntax errors, tracebacks, and linter warnings do not pollute the terminal buffer or trigger automated safety traps.
