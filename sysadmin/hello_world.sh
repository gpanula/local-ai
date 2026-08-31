#!/bin/bash

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"

# Binary checks
[ -x "${VENV_DIR}/bin/python" ] || { echo "Python binary not found or not executable in ${VENV_DIR}/bin"; exit 1; }
[ -x "${VENV_DIR}/bin/ansible-lint" ] || { echo "Ansible-lint binary not found or not executable in ${VENV_DIR}/bin"; exit 1; }

# Strict mode flags
set -euo pipefail

# Trap handlers
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
trap 'echo "Cleanup actions here if needed"' EXIT

# Main functionality
echo "Hello from Ollama Multi-Agent Pipeline"

echo "🎉 Hello World test completed successfully"
exit 0