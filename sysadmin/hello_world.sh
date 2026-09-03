#!/bin/bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"
[ -x "${VENV_DIR}/bin/shellcheck" ] || { echo "❌ [ERROR] shellcheck not found in VENV" >&2; exit 1; }
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
echo "Hello from Ollama Multi-Agent Pipeline"
echo "🎉 Hello World test completed successfully"
exit 0