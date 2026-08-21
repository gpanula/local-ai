# Task Specification: Provision & Verify P0 Toolchain Virtual Environment

## Objective
Author and execute a standalone, resilient Bash script that provisions a dedicated Python virtual environment at `sysadmin/venv`, installs the P0 developer toolchain (`ansible`, `ansible-lint`, `shellcheck-py`, `pyyaml`), and rigorously asserts the health of every installed tool before reporting success.

---

## 1. Environment & Target Specifications
* **Target Directory**: `sysadmin/venv` (relative to the repository root).
* **Virtual Environment Creation**:
  * Attempt `python3 -m venv "${VENV_DIR}"`. If `ensurepip` is absent (Debian/Ubuntu default), create the environment using `python3 -m venv --without-pip "${VENV_DIR}"`.
* **Packaging Bootstrap**:
  * If `pip` is absent in `${VENV_DIR}/bin/pip`, download `get-pip.py` (`curl -sSL https://bootstrap.pypa.io/get-pip.py -o "${TEMP_DIR}/get-pip.py" -H "User-Agent: Python"`) and run `"${VENV_DIR}/bin/python3" "${TEMP_DIR}/get-pip.py"`.
  * Upgrade core packaging tools: `"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel`.
* **Required Package Installations**:
  * `ansible` (provides `${VENV_DIR}/bin/ansible`)
  * `ansible-lint` (provides `${VENV_DIR}/bin/ansible-lint`)
  * `shellcheck-py` (provides the `${VENV_DIR}/bin/shellcheck` binary)
  * `pyyaml` (provides the `yaml` Python module)

---

## 2. Defensive Error Handling & Quality Requirements
All synthesized code must strictly adhere to the project's **Defensive Scripting Standards**:
1. **Strict Error Flags**: Must enable `set -euo pipefail`.
2. **Diagnostic Error Traps**: Must install a trap for `ERR` signals that prints the failed line number and command before terminating:
   ```bash
   trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR
   ```
3. **Scratch Resource Cleanup & Directory Resilience**:
   * Must ensure scratch parent directories exist before creating temporary folders (e.g. `mkdir -p "${TMPDIR:-/tmp}"` and `TEMP_DIR=$(mktemp -d -p /tmp 2>/dev/null || mktemp -d "/tmp/setup_p0_XXXXXX")`).
   * Must register an `EXIT` trap (e.g. `trap 'rm -rf "${TEMP_DIR:-}"' EXIT`) to delete any temporary download files or scratch directories.
4. **Post-Installation Binary Assertions**: Explicitly verify that each expected binary exists in `${VENV_DIR}/bin/` and is executable:
   * Test binary executables: `python`, `pip`, `ansible`, `ansible-lint`, `shellcheck` via `[ -x "${VENV_DIR}/bin/<name>" ]`.
   * Test Python library import: `"${VENV_DIR}/bin/python" -c "import yaml; print(yaml.__version__)"`.
5. **Functional Smoke Tests & Sandbox Resilience**:
   * Run `--version` sanity checks for `ansible`, `ansible-lint`, and `shellcheck`.
   * *Sandbox Requirement*: When running Ansible checks, ensure `ANSIBLE_LOCAL_TEMP` and `ANSIBLE_HOME` point to a writable temporary directory created with explicit `-p /tmp` (such as `ANSIBLE_LOCAL_TEMP=$(mktemp -d -p /tmp 2>/dev/null || mktemp -d "/tmp/ansible-check-XXXXXX")`) to prevent read-only filesystem errors on `~/.ansible`.
6. **Guarded Success Gate**:
   * Emit version details and the final success banner (`🎉 P0 toolchain virtual environment ready at: ...`) **ONLY** if all binary assertions and smoke tests pass without triggering error traps.

---

## 3. Output Contract & Execution Requirements
* The LLM must synthesize the complete script and write it via a Bash heredoc to:
  `sysadmin/setup_p0_toolchain.sh`
* Grant execute permissions: `chmod +x sysadmin/setup_p0_toolchain.sh`
* Immediately execute the script: `./sysadmin/setup_p0_toolchain.sh`
* Respond ONLY with the executable `bash` block containing the heredoc, chmod, and execution command.
