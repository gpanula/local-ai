# Task: Create & Execute Python Virtual Environment with Manual Pip Bootstrap

## Goal
Generate and execute a standalone Bash heredoc command that creates a Python virtual environment at `test_venv` with `--without-pip`, manually bootstraps `pip` into `test_venv/bin/pip` using `get-pip.py`, and immediately executes the script to verify the binaries.

---

## Technical Specifications
* **Virtual Environment**: Use `python3 -m venv --without-pip test_venv`.
* **Pip Bootstrap**: Download `get-pip.py` to `/tmp/get-pip.py` using Python's `urllib.request` (with `User-Agent: Mozilla/5.0`) or `curl -fsSL -A "Mozilla/5.0" https://bootstrap.pypa.io/get-pip.py`, then run `test_venv/bin/python /tmp/get-pip.py --no-setuptools --no-wheel`.
* **Cleanup**: Delete `/tmp/get-pip.py`.
* **Verification**: Print `test_venv/bin/python --version` and `test_venv/bin/pip --version`.

---

## Mandatory Output Format
Respond ONLY with the complete executable `bash` code block. Do NOT review or critique the prompt; output the bash command to build and run the script:

```bash
cat << 'EOF' > sysadmin/test_simple_venv.sh
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
EOF

chmod +x sysadmin/test_simple_venv.sh
./sysadmin/test_simple_venv.sh
```
