# Lessons Learned — Episodic Memory Store

> **Purpose**: Git-canonical store of approved episodic lessons, promoted from the
> pending review queue via the `review-lessons` CLI. Each lesson is a YAML-frontmatter
> block followed by the rule text.
>
> **Format** (see `ai_memory_summary.md` §Canonical File Formats):
>
> ```markdown
> ---
> id: lesson-YYYYMMDD-NN
> category: <category>
> keywords: [kw1, kw2, kw3]
> created: YYYY-MM-DD
> source_task: <path/to/prompt.md>
> ---
> **Rule**: <rule text>
> ```

<!-- Lessons are appended below this line by the review-lessons promotion flow. -->

---
id: lesson-20260830-03
category: Binary Isolation
keywords: [ansible, ansible sandbox isolation, bash, bash scripting, binary assertions, binary existence check, binary isolation, code quality, functional test suites, linters, pre-execution assertions, pre-flight linters, python, python syntax validation, virtual environment, yaml, yaml parsing]
created: 2026-08-30
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: When developing a standalone, portable Bash verification script for code quality and pre-flight linters toolchain, ensure that the script resolves the virtual environment path deterministically and safely. Also, explicitly invoke all required binaries from the virtual environment's bin directory to maintain binary isolation. Before executing functional test suites, assert that all required binaries exist and are executable.

---
id: lesson-20260830-13
category: ShellCheck
keywords: [codes, linter, loop, pre-flight, sc1003, sc1009, sc1050, sc1064, sc1065, sc1072, sc1073, sc1078, sc1079, sc2034, shellcheck, stuck, styleguidelines, variablenaming]
created: 2026-08-30
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: Ensure that all ShellCheck linter findings (SC1003, SC1009, SC1050, SC1064, SC1065, SC1072, SC1073, SC1078, SC1079) are addressed in the `sysadmin/prompts/verify_code_quality_toolchain.sh` script before deployment.

---
id: lesson-20260830-14
category: Docker Orchestration
keywords: [docker, compose]
created: 2026-08-30
source_task: 
---
**Rule**: Always check docker daemon health before running compose.

---
id: lesson-20260918-01
category: Defensive Bash Scripting
keywords: [error handling, traps, environment variables, path resolution]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Implement robust error handling, environment variable resolution, and resource cleanup traps in scripts to ensure reliability and compliance with operational standards.

---
id: lesson-20260918-02
category: Binary Isolation
keywords: [ERR Trap, Exit Code 0, Success Message, Virtual Environment, Binary Existence]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Implement ERR trap for error diagnostics, explicitly exit 0 on success, include success message with required emoji, resolve REPO_ROOT/VENV_DIR variables, and verify binary existence via [ -x "${VENV_DIR}/bin/shellcheck" ] before execution.

---
id: lesson-20260918-03
category: Defensive Bash Scripting
keywords: [success message, environment variables, error handling, exit code 0]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Ensure scripts use the correct success message matching task requirements, resolve all required environment variables (REPO_ROOT/VENV_DIR) deterministically, and guard success messages with explicit error checks to guarantee exit code 0 compliance

---
id: lesson-20260918-05
category: Defensive Bash Scripting
keywords: [virtual environment resolution, binary existence assertion, EXIT trap]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Always resolve REPO_ROOT and VENV_DIR deterministically, assert existence of binaries via explicit paths, and implement EXIT traps for cleanup to comply with universal system rules and defensive standards.

---
id: lesson-20260918-09
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, coder]
created: 2026-09-18
source_task: runs/run-20260909-043422-8fc76f/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for coder: Potential risks include script failures due to missing dependencies or incorrect environment variabl -> Solved via: The solution involves embedding the bash script directly in the output, ensuring it adheres to defen

---
id: lesson-20260918-11
category: audit
keywords: [approved, audit pass, no risks]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no risks should be automatically approved.

---
id: lesson-20260918-13
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, coder]
created: 2026-09-18
source_task: runs/run-20260916-041133-286ca9/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for coder: Potential risks include script failures and incorrect exit codes. Defensive safeguards ensure the sc -> Solved via: The script is embedded directly in the output, ensuring it's self-contained and compliant with defen

---
id: lesson-20260918-16
category: Multi-Agent Orchestration
keywords: [approved, audit pass, no risks]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-30
category: Script Creation and Execution
keywords: [bash script, defensive standards, exit cleanly, write_file tool]
created: 2026-09-18
source_task: runs/run-20260916-054359-6e3734/messages/annotated_plan.json
---
**Rule**: Create a bash script using the `write_file` tool with the necessary content, enable defensive standards, and ensure it exits with code 0 when executed.

---
id: lesson-20260918-35
category: Defensive Bash Scripting
keywords: [Unicode, success message, bash script]
created: 2026-09-18
source_task: # Task: Hello World Multi-Agent Pipeline Test

## Goal
Write and execute a standalone bash script at
---
**Rule**: Ensure that success messages in bash scripts use the correct Unicode character. For instance, use '\ud83c\udf89' for a party popper emoji instead of '\u274c' for a cross mark.

---
id: lesson-20260918-37
category: Security & Hardening
keywords: [bash script, defensive standards, risk mitigation, tool verification]
created: 2026-09-18
source_task: runs/run-20260918-042512-51805f/messages/annotated_plan.json
---
**Rule**: Ensure all bash scripts include defensive measures such as set -euo pipefail, ERR traps, and proper exit codes, and verify that execution tools like run_bash are permitted and sandboxed to prevent unsafe operations.

---
id: lesson-20260929-01
category: Defensive Bash Scripting
keywords: [bash, scripting, trap, err, set -euo pipefail, REPO_ROOT, VENV_DIR, binary assertions]
created: 2026-09-29
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Always enable `set -euo pipefail`, register an ERR trap (`trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR`), deterministically resolve `REPO_ROOT` and `VENV_DIR`, and assert binary existence (`[ -x ... ]`) before emitting success.

---
id: lesson-20260929-02
category: Binary Isolation
keywords: [binary, venv, virtual environment, binary isolation, binary assertions, deterministic resolution, hardcoded paths]
created: 2026-09-29
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: Never rely on ambient $PATH. Deterministically resolve virtual envs (`VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"`) and invoke tools via explicit paths (`"${VENV_DIR}/bin/<binary>"`). Avoid hardcoding `/home/...` paths.

---
id: lesson-20260929-03
category: ShellCheck
keywords: [shellcheck, sc2086, sc2034, quoting, linters, variable naming]
created: 2026-09-29
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: Ensure all variables are double-quoted to prevent word splitting (SC2086), remove unreferenced variables (SC2034), and pass pre-flight ShellCheck verification.

---
id: lesson-20260929-04
category: Defensive Bash Scripting
keywords: [bash, negative assertions, error handling, syntax testing, exit codes, set -e, failure detection, python ast, yaml, shellcheck, ansible]
created: 2026-09-29
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: When testing negative assertions in defensive Bash scripts (verifying that invalid syntax, malformed configurations, or flawed scripts fail parsing as expected), NEVER write `if ! command; then echo "Validation failed"; exit 1; fi` — the exclamation mark inverts the command's expected non-zero error exit into success (0), causing the error branch to trigger and abort the script! Instead, directly test the command without negation and abort only if the command unexpectedly succeeds: `if "${VENV_DIR}/bin/python" -c "import ast; ast.parse('invalid syntax')" >/dev/null 2>&1; then echo "❌ Failed to catch syntax error"; exit 1; fi`. Always redirect both stdout and stderr (`>/dev/null 2>&1`) so that expected syntax errors, tracebacks, and linter warnings do not pollute the terminal buffer or trigger automated safety traps.

---
id: lesson-20261012-01
category: Audit Compliance
keywords: [Audit Pass, No Risks, Approved Verdict, Pre-filter Routing, Test Compliance]
created: 2026-10-12
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: Approve test runs with no violations and verified audit compliance.
