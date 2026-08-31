# Task Specification: Verify Code Quality & Pre-Flight Linters Toolchain

## Objective
Author and execute a standalone, portable Bash verification script at `sysadmin/verify_code_quality_toolchain.sh` that validates the installation, configuration, and functional behavior of all Section 1 tools (**Code Quality & Pre-Flight Linters**) from `sysadmin/mcp_ollama/TOOLS_ROADMAP.md`.

---

## 1. Environment & Architectural Constraints
* **Target Script Path**: `sysadmin/verify_code_quality_toolchain.sh` (relative to repository root).
* **Virtual Environment Resolution ([Rule 4 `AGENTS.md`](../../AGENTS.md))**:
  * Default to `${REPO_ROOT}/sysadmin/venv` or accept an optional first argument (`$1`) for custom virtual environment paths.
  * Must deterministically resolve the repository root and virtual environment path in a manner safe for subshell/sourced execution without relying on ambient `$PATH` or unbound variables under `set -u`.
* **Explicit Virtual Environment Binary Isolation ([Rule 4 `AGENTS.md`](../../AGENTS.md))**:
  * All test suites and assertions MUST invoke binaries directly from `${VENV_DIR}/bin/` (e.g. `python`, `pip`, `ansible`, `ansible-playbook`, `ansible-lint`, `shellcheck`), never relying on global system `$PATH`.
* **Pre-Execution Binary Assertions**:
  * Assert that all required binaries exist in `${VENV_DIR}/bin/` and are executable (`[ -x ... ]`) before proceeding to functional test suites.

---

## 2. Functional Test Suites & Interface Contracts

The script must execute 4 discrete test suites and report clear pass/fail diagnostics for each:

### Suite 1: Python AST & PyYAML In-Memory Validation
* Validate in-memory Python syntax parsing using `ast.parse()` and YAML parsing using `yaml.safe_load()`.
* Validate negative error detection by verifying that invalid Python syntax and invalid YAML structures fail parsing and are properly handled.

### Suite 2: Ansible Syntax Check & Sandbox Isolation
* Enforce sandbox isolation by directing Ansible runtime directories (`ANSIBLE_HOME`, `ANSIBLE_LOCAL_TEMP`) to a writable temporary directory in `/tmp`.
* Validate positive syntax checking by running `ansible-playbook --syntax-check` against a temporary valid minimal playbook.
* Validate negative syntax checking by ensuring an invalid playbook syntax fails with a non-zero exit code.

### Suite 3: Ansible Lint Verification
* Assert `ansible-lint --version` executes cleanly.
* Execute `ansible-lint` against the temporary test playbook and verify execution.

### Suite 4: ShellCheck Static Analysis
* Assert `shellcheck --version` executes cleanly.
* Validate clean script analysis: verify that a clean, defensively-written script passes ShellCheck with exit code 0.
* Validate fault detection: verify that a script containing flawed syntax or unquoted variable expansion is caught by ShellCheck with a non-zero exit code. Ensure test fixtures are isolated in temporary files so the verification script itself produces zero ShellCheck warnings.

---

## 3. Defensive Error Handling & Quality Standards
All synthesized code must strictly adhere to the project's **Defensive Scripting Standards ([Rule 4 `AGENTS.md`](../../AGENTS.md))**:
1. **Strict Error Flags**: Enable `set -euo pipefail`.
2. **Diagnostic Error Traps**: Install an `ERR` trap that prints the failed line number and the command that triggered the failure.
3. **Direct Conditional Exit Checking**: Check command success or failure directly in conditional statements (e.g. `if command; then` or `if ! command; then`) rather than indirect `$?` checks, ensuring full compatibility with `set -e` and zero ShellCheck SC2181 findings.
4. **Scratch Resource Cleanup & Directory Resilience**:
   * Ensure scratch parent directories exist before creating temporary folders and explicitly use `/tmp`.
   * Install an `EXIT` trap to clean up all temporary test files, playbooks, and directories upon script termination.
5. **Zero ShellCheck Findings**: The synthesized verification script itself must be 100% clean and produce zero ShellCheck warnings or errors.
6. **Guarded Success Gate**: Emit component summary diagnostics and the final success banner (`🎉 Code Quality & Pre-Flight Linters verification passed!`) ONLY if all test suites pass without triggering error traps.

---

## 4. Output Contract
The synthesized script must be a complete standalone Bash script starting with `#!/bin/bash` designed to reside at `sysadmin/verify_code_quality_toolchain.sh`. Emit the script code directly inside a ```bash code block or via a write_file tool call. (Do not generate wrapper installer functions or nested heredoc script-writers).
