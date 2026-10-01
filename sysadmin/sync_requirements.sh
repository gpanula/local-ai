#!/usr/bin/env bash
# ==============================================================================
# sync_requirements.sh - Synchronize and audit sysadmin/requirements.txt
# ==============================================================================
set -euo pipefail
trap 'echo "❌ [ERROR] Line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
VENV_DIR="${REPO_ROOT}/sysadmin/venv"
PYTHON_BIN="${VENV_DIR}/bin/python3"
REQUIREMENTS_FILE="${REPO_ROOT}/sysadmin/requirements.txt"
TEMP_DIR=$(mktemp -d -p /tmp)
trap 'rm -rf "${TEMP_DIR:-}"' EXIT

CHECK_MODE=0
if [ "${1:-}" = "--check" ]; then
    CHECK_MODE=1
fi

# Fallback to system python3 if venv not yet initialized
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="$(command -v python3 || echo "")"
    if [ -z "${PYTHON_BIN}" ]; then
        echo "❌ [ERROR] No python3 interpreter found." >&2
        exit 1
    fi
fi

TARGET_TMP="${TEMP_DIR}/requirements.txt.new"

"${PYTHON_BIN}" - "${REQUIREMENTS_FILE}" "${TARGET_TMP}" << 'EOF'
import os
import sys

req_path = sys.argv[1]
out_path = sys.argv[2]

core_packages = [
    "ansible",
    "ansible-lint",
    "pytest",
    "pyyaml",
    "rich",
    "shellcheck-py",
    "sqlite-vec",
    "textual",
    "zstandard",
]

packages = set(core_packages)

if os.path.exists(req_path):
    with open(req_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                packages.add(line.lower())

with open(out_path, "w", encoding="utf-8") as f:
    for pkg in sorted(packages):
        f.write(f"{pkg}\n")
EOF

FILE_CHANGED=0
if [ ! -f "${REQUIREMENTS_FILE}" ] || ! cmp -s "${TARGET_TMP}" "${REQUIREMENTS_FILE}"; then
    FILE_CHANGED=1
    if [ "${CHECK_MODE}" -eq 0 ]; then
        cp "${TARGET_TMP}" "${REQUIREMENTS_FILE}"
        echo "📦 [Requirements Sync] Updated ${REQUIREMENTS_FILE}."
    fi
fi

# Check for uncommitted differences in git
STATUS_DIFF="$(git -C "${REPO_ROOT}" status --porcelain "${REQUIREMENTS_FILE}" 2>/dev/null || true)"

if [ "${CHECK_MODE}" -eq 1 ]; then
    if [ "${FILE_CHANGED}" -eq 1 ] || [ -n "${STATUS_DIFF}" ]; then
        echo "⛔ [Requirements Drift] sysadmin/requirements.txt has uncommitted changes or package drift:" >&2
        git -C "${REPO_ROOT}" diff "${REQUIREMENTS_FILE}" >&2 || true
        exit 1
    else
        echo "✅ [Requirements Check] sysadmin/requirements.txt is in sync and clean."
    fi
else
    if [ "${FILE_CHANGED}" -eq 0 ] && [ -z "${STATUS_DIFF}" ]; then
        echo "✅ [Requirements Sync] sysadmin/requirements.txt is already in sync and clean."
    fi
fi
