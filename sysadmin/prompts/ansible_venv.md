# Task: Create & Execute Ansible Virtual Environment Setup (Self-Contained Bootstrap)

## Goal
Create a standalone Python virtual environment at `sysadmin/ansible` with `pip`, `setuptools`, `wheel`, `ansible`, and `ansible-lint` installed directly inside `sysadmin/ansible/bin/`, without depending on the system's `ensurepip` or `python3-venv` OS packages.

---

## Environmental Constraints & Ground Rules
* **No OS Ensurepip Dependency**: Debian/Ubuntu minimal environments lack `ensurepip`/`python3-venv`. You MUST create the virtual environment using `python3 -m venv --without-pip "${VENV_DIR}"`. Do NOT attempt `python3 -m venv` without the `--without-pip` flag.
* **Pip Bootstrapping**: Bootstrap `pip` inside the virtual environment using Python's built-in `urllib.request` (with a custom User-Agent to prevent CDN HTTP 403 blocks) or `curl -fsSL -A "Mozilla/5.0" https://bootstrap.pypa.io/get-pip.py` to download `get-pip.py` to `/tmp/get-pip.py`, then invoke `"${VENV_DIR}/bin/python" /tmp/get-pip.py --no-setuptools --no-wheel`.
* **Clean Cleanup**: Ensure `/tmp/get-pip.py` is deleted immediately after execution.
* **Self-Contained Package Installs**:
  * Upgrade `pip`, `setuptools`, `wheel` inside the environment using `"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel`.
  * Install `ansible` and `ansible-lint` using `"${VENV_DIR}/bin/pip" install ansible ansible-lint`.
* **Smoke Testing & Verification**:
  * Verify `"${VENV_DIR}/bin/python" --version`
  * Verify `"${VENV_DIR}/bin/pip" --version`
  * Verify `"${VENV_DIR}/bin/ansible" --version | head -n 1`
  * Verify `"${VENV_DIR}/bin/ansible-lint" --version | head -n 1`

---

## Output Directives
Generate the complete implementation as a single executable Bash heredoc command that creates `sysadmin/setup_ansible_env.sh`, permissions it, and runs it live:

```bash
cat << 'EOF' > sysadmin/setup_ansible_env.sh
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/ansible"
TMP_GET_PIP="$(mktemp /tmp/get-pip-XXXXXX.py)"
trap 'rm -f "${TMP_GET_PIP}"' EXIT

echo "==> Step 1: Creating virtual environment (without-pip) at ${VENV_DIR}"
rm -rf "${VENV_DIR}"
python3 -m venv --without-pip "${VENV_DIR}"

echo "==> Step 2: Bootstrapping pip into ${VENV_DIR}"
python3 -c "
import urllib.request
req = urllib.request.Request('https://bootstrap.pypa.io/get-pip.py', headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=30) as resp, open('${TMP_GET_PIP}', 'wb') as f:
    f.write(resp.read())
" || curl -fsSL -A "Mozilla/5.0" https://bootstrap.pypa.io/get-pip.py -o "${TMP_GET_PIP}"

"${VENV_DIR}/bin/python" "${TMP_GET_PIP}" --no-setuptools --no-wheel

echo "==> Step 3: Upgrading base packaging tools"
"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel

echo "==> Step 4: Installing Ansible and ansible-lint"
"${VENV_DIR}/bin/pip" install ansible ansible-lint

echo "==> Step 5: Verifying installation"
echo "----------------------------------------"
echo "Python binary: $("${VENV_DIR}/bin/python" --version)"
echo "Pip binary:    $("${VENV_DIR}/bin/pip" --version)"
echo "Ansible:       $("${VENV_DIR}/bin/ansible" --version | head -n 1)"
echo "Ansible-Lint:  $("${VENV_DIR}/bin/ansible-lint" --version | head -n 1)"
echo "----------------------------------------"
echo "🎉 Ansible virtual environment setup complete at: ${VENV_DIR}"
EOF

chmod +x sysadmin/setup_ansible_env.sh
./sysadmin/setup_ansible_env.sh
```
