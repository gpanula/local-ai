#!/bin/bash
# setup_graphify.sh - Install and verify graphify in the local-ai virtual environment
# Standard: set -euo pipefail, ERR/EXIT traps, deterministic venv resolution

set -euo pipefail

# Deterministically locate repo root and virtualenv
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"
GRAPHIFY_BIN="${VENV_DIR}/bin/graphify"
PIP_BIN="${VENV_DIR}/bin/pip"
PYTHON_BIN="${VENV_DIR}/bin/python"

TMP_DIR="$(mktemp -d -p /tmp graphify_setup.XXXXXX)"

trap 'echo "❌ [ERROR] Line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR
trap 'rm -rf "${TMP_DIR:-}"' EXIT

echo "🔍 Checking virtual environment at: ${VENV_DIR}"
if [ ! -d "${VENV_DIR}" ] || [ ! -x "${PYTHON_BIN}" ]; then
    echo "Creating virtual environment at: ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
fi

echo "📦 Upgrading pip and setuptools..."
"${PIP_BIN}" install --upgrade pip setuptools wheel

echo "📥 Installing graphifyy (Graphify CLI and dependencies)..."
"${PIP_BIN}" install graphifyy

echo "🔍 Verifying graphify binary and importability..."
if [ ! -x "${GRAPHIFY_BIN}" ]; then
    echo "❌ [ERROR] graphify binary not found or not executable at: ${GRAPHIFY_BIN}" >&2
    exit 1
fi

# Verify Python importability and AST parsing capability
"${PYTHON_BIN}" -c "import graphify; print('✅ Successfully imported graphify module version:', getattr(graphify, '__version__', 'unknown'))"

echo "🧪 Running smoke test..."
"${GRAPHIFY_BIN}" --help > "${TMP_DIR}/help.txt"
grep -q "graphify" "${TMP_DIR}/help.txt"

echo "🎉 Graphify successfully installed and verified at: ${GRAPHIFY_BIN}"
