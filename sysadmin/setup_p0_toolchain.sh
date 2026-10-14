#!/usr/bin/env bash

# Enable strict error handling
set -euo pipefail

# Deterministic directory resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"
REQUIREMENTS_FILE="${REPO_ROOT}/sysadmin/requirements.txt"
TEMP_DIR=$(mktemp -d -p /tmp)

# Trap for ERR signals
trap 'echo "❌ [ERROR] Line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

# Trap for EXIT signals to clean up temporary files
trap 'rm -rf "${TEMP_DIR:-}" "${ANSIBLE_LOCAL_TEMP:-}"' EXIT

# Function to create virtual environment
create_venv() {
    if [ ! -d "${VENV_DIR}" ]; then
        python3 -m venv "${VENV_DIR}"
    fi
}

# Function to install pip if not available
install_pip() {
    if [ ! -x "${VENV_DIR}/bin/pip" ]; then
        echo "Installing pip into virtual environment..."
        curl -sSL https://bootstrap.pypa.io/get-pip.py -o "${TEMP_DIR}/get-pip.py" -H "User-Agent: Python"
        "${VENV_DIR}/bin/python" "${TEMP_DIR}/get-pip.py"
    fi
}

# Function to upgrade packaging tools
upgrade_pip_tools() {
    "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
}

# Function to install required packages
install_packages() {
    if [ -f "${REQUIREMENTS_FILE}" ]; then
        echo "📦 Installing packages from ${REQUIREMENTS_FILE}..."
        "${VENV_DIR}/bin/pip" install --upgrade -r "${REQUIREMENTS_FILE}"
    else
        echo "⚠️  [WARN] ${REQUIREMENTS_FILE} not found; falling back to hardcoded package list..."
        "${VENV_DIR}/bin/pip" install --upgrade ansible ansible-lint shellcheck-py pyyaml pytest sqlite-vec rich textual zstandard
    fi
}

# Function to verify package installation
verify_packages() {
    for tool in ansible ansible-lint shellcheck; do
        if ! [ -x "${VENV_DIR}/bin/${tool}" ]; then
            echo "Error: ${tool} is not installed or not executable."
            exit 1
        fi
    done

    # Verify Python library import
    if ! "${VENV_DIR}/bin/python" -c "import yaml, rich, textual, zstandard; print(yaml.__version__)" &> /dev/null; then
        echo "Error: required python libraries are not installed or not importable."
        exit 1
    fi
}

# Function to run smoke tests
run_smoke_tests() {
    # Set environment variables for Ansible
    export ANSIBLE_LOCAL_TEMP=$(mktemp -d -p /tmp)
    export ANSIBLE_HOME="${ANSIBLE_LOCAL_TEMP}"

    # Run smoke tests
    "${VENV_DIR}/bin/ansible" --version
    "${VENV_DIR}/bin/ansible-lint" --version
    "${VENV_DIR}/bin/shellcheck" --version

    # Clean up Ansible temporary directory
    rm -rf "${ANSIBLE_LOCAL_TEMP}"
}

# Main script execution
create_venv
install_pip
upgrade_pip_tools
install_packages
verify_packages
run_smoke_tests

# Guarded success gate
echo "🎉 P0 toolchain virtual environment ready at: ${VENV_DIR}"
