#!/bin/bash
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
trap 'rm -rf "$TEMP_DIR"' EXIT

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"
TEMP_DIR="/tmp/verify_code_quality_toolchain_$$"
mkdir -p "$TEMP_DIR"

# Suite 1: Python AST & PyYAML In-Memory Validation
if [ ! -x "${VENV_DIR}/bin/python" ]; then
echo "❌ Python binary not found or not executable in ${VENV_DIR}/bin/"
exit 1
fi

"${VENV_DIR}/bin/python" -c "import ast; ast.parse('def foo(): pass')" >/dev/null 2>&1
"${VENV_DIR}/bin/python" -c "import yaml; yaml.safe_load('key: value')" >/dev/null 2>&1
if ! "${VENV_DIR}/bin/python" -c "import ast; ast.parse('def foo() pass')" >/dev/null 2>&1; then
echo "❌ Python AST validation failed"
exit 1
fi
if ! "${VENV_DIR}/bin/python" -c "import yaml; yaml.safe_load(': invalid yaml')" >/dev/null 2>&1; then
echo "❌ PyYAML validation failed"
exit 1
fi
echo "✅ Suite 1 passed"

# Suite 2: Ansible Syntax Check & Sandbox Isolation
if [ ! -x "${VENV_DIR}/bin/ansible-playbook" ]; then
echo "❌ ansible-playbook binary not found or not executable in ${VENV_DIR}/bin/"
exit 1
fi

cat > "$TEMP_DIR/test_playbook.yml" <<'EOF'
- hosts: localhost
tasks:
  - name: Test task
    command: echo Hello World
EOF
cat > "$TEMP_DIR/invalid_playbook.yml" <<'EOF'
- hosts: localhost
tasks:
  - name: Test task
    command: echo Hello World
  - name: Invalid task
    command: echo Missing colon
EOF
ANSIBLE_HOME="$TEMP_DIR"
ANSIBLE_LOCAL_TEMP="$TEMP_DIR"
export ANSIBLE_HOME ANSIBLE_LOCAL_TEMP

"${VENV_DIR}/bin/ansible-playbook" --syntax-check "$TEMP_DIR/test_playbook.yml" >/dev/null 2>&1
if ! "${VENV_DIR}/bin/ansible-playbook" --syntax-check "$TEMP_DIR/invalid_playbook.yml" >/dev/null 2>&1; then
echo "❌ Ansible syntax check failed"
exit 1
fi
echo "✅ Suite 2 passed"

# Suite 3: Ansible Lint Verification
if [ ! -x "${VENV_DIR}/bin/ansible-lint" ]; then
echo "❌ ansible-lint binary not found or not executable in ${VENV_DIR}/bin/"
exit 1
fi

"${VENV_DIR}/bin/ansible-lint" --version >/dev/null 2>&1
"${VENV_DIR}/bin/ansible-lint" "$TEMP_DIR/test_playbook.yml" >/dev/null 2>&1
echo "✅ Suite 3 passed"

# Suite 4: ShellCheck Static Analysis
if [ ! -x "${VENV_DIR}/bin/shellcheck" ]; then
echo "❌ shellcheck binary not found or not executable in ${VENV_DIR}/bin/"
exit 1
fi

cat > "$TEMP_DIR/clean_script.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
echo "Hello World"
EOF
cat > "$TEMP_DIR/flawed_script.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
echo Hello World
EOF

"${VENV_DIR}/bin/shellcheck" --version >/dev/null 2>&1
"${VENV_DIR}/bin/shellcheck" "$TEMP_DIR/clean_script.sh" >/dev/null 2>&1
if "${VENV_DIR}/bin/shellcheck" "$TEMP_DIR/flawed_script.sh" >/dev/null 2>&1; then
echo "❌ ShellCheck failed to detect flawed script"
exit 1
fi
echo "✅ Suite 4 passed"

echo "🎉 Code Quality & Pre-Flight Linters verification passed!"
