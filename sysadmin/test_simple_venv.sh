#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="test_venv"
TMP_GET_PIP="$(mktemp /tmp/get-pip-XXXXXX.py)"
trap 'rm -f "${TMP_GET_PIP}"' EXIT

echo "==> Step 1: Creating virtual environment with --without-pip at: ${VENV_DIR}"
rm -rf "${VENV_DIR}"
python3 -m venv --without-pip "${VENV_DIR}"

echo "==> Step 2: Bootstrapping pip into ${VENV_DIR}/bin/pip"
python3 -c "
import urllib.request
req = urllib.request.Request('https://bootstrap.pypa.io/get-pip.py', headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=30) as resp, open('${TMP_GET_PIP}', 'wb') as f:
    f.write(resp.read())
" || curl -fsSL -A "Mozilla/5.0" https://bootstrap.pypa.io/get-pip.py -o "${TMP_GET_PIP}"

"${VENV_DIR}/bin/python" "${TMP_GET_PIP}" --no-setuptools --no-wheel

echo ""
echo "==> Step 3: Verifying Virtual Environment Binaries:"
echo "--------------------------------------------------"
echo "Python binary: $("${VENV_DIR}/bin/python" --version)"
echo "Pip binary:    $("${VENV_DIR}/bin/pip" --version)"
echo "--------------------------------------------------"
echo "🎉 Virtual environment with pip successfully created at: ${VENV_DIR}"
