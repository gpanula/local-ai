#!/bin/bash

# Enable strict error handling
set -euo pipefail

# Define variables
VENV_DIR="sysadmin/venv"
TEMP_DIR=$(mktemp -d)

# Trap for ERR signals
trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR

# Trap for EXIT signals to clean up temporary files
trap 'rm -rf "${TEMP_DIR:-}"' EXIT

# Function to create virtual environment
create_venv() {
    if [ ! -d "${VENV_DIR}" ]; then
        python -m venv "${VENV_DIR}"
    fi
}

# Function to install pip if not available
install_pip() {
    if ! command -v pip &> /dev/null; then
        echo "Installing pip..."
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
    "${VENV_DIR}/bin/pip" install ansible ansible-lint shellcheck-py pyyaml
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
    if ! "${VENV_DIR}/bin/python" -c "import yaml; print(yaml.__version__)" &> /dev/null; then
        echo "Error: pyyaml is not installed or not importable."
        exit 1
    fi
}

# Function to run smoke tests
run_smoke_tests() {
    # Set environment variables for Ansible
    export ANSIBLE_LOCAL_TEMP=$(mktemp -d)
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
