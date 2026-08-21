#!/usr/bin/env bash

set -euo pipefail

trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR
TEMP_DIR=$(mktemp -d -p /tmp 2>/dev/null || mktemp -d "/tmp/setup_p0_XXXXXX")
trap 'rm -rf "${TEMP_DIR:-}"' EXIT

VENV_DIR="sysadmin/venv"
mkdir -p "$(dirname "${VENV_DIR}")"

if ! python3 -m venv --help | grep -q -- "--without-pip"; then
  python3 -m venv "${VENV_DIR}"
else
  python3 -m venv --without-pip "${VENV_DIR}"
fi

if [ ! -x "${VENV_DIR}/bin/pip" ]; then
  curl -sSL https://bootstrap.pypa.io/get-pip.py -o "${TEMP_DIR}/get-pip.py" -H "User-Agent: Python"
  "${VENV_DIR}/bin/python3" "${TEMP_DIR}/get-pip.py"
fi

"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install ansible ansible-lint shellcheck-py pyyaml

for binary in python pip ansible ansible-lint shellcheck; do
  [ -x "${VENV_DIR}/bin/${binary}" ] || { echo "❌ Failed to find ${binary}"; exit 1; }
done

"${VENV_DIR}/bin/python" -c "import yaml; print(yaml.__version__)" > /dev/null

ANSIBLE_LOCAL_TEMP=$(mktemp -d -p /tmp 2>/dev/null || mktemp -d "/tmp/ansible-check-XXXXXX")
export ANSIBLE_LOCAL_TEMP ANSIBLE_HOME="${ANSIBLE_LOCAL_TEMP}"
trap 'rm -rf "${ANSIBLE_LOCAL_TEMP:-}"' EXIT

for binary in ansible ansible-lint shellcheck; do
  "${VENV_DIR}/bin/${binary}" --version > /dev/null || { echo "❌ Failed to run ${binary} --version"; exit 1; }
done

echo "🎉 P0 toolchain virtual environment ready at: ${VENV_DIR}"
