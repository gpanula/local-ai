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
echo "Python binary not found in ${VENV_DIR}/bin/"
exit 1
fi

"${VENV_DIR}/bin/python" -c "import ast, yaml; ast.parse('def foo(): pass'); yaml.safe_load('{}')"
if ! "${VENV_DIR}/bin/python" -c "import ast; ast.parse('def foo() pass')" >/dev/null 2>&1; then
echo "Python syntax error detected as expected"
else
echo "Python syntax error not detected"
exit 1
fi

if ! "${VENV_DIR}/bin/python" -c "import yaml; yaml.safe_load('{')" >/dev/null 2>&1; then
echo "YAML syntax error detected as expected"
else
echo "YAML syntax error not detected"
exit 1
fi

echo "Suite 1 passed"

# Suite 2: Ansible Syntax Check & Sandbox Isolation
if [ ! -x "${VENV_DIR}/bin/ansible-playbook" ]; then
echo "Ansible-playbook binary not found in ${VENV_DIR}/bin/"
exit 1
fi

cat > "$TEMP_DIR/playbook.yml" <<'EOF'
- hosts: localhost
tasks:
  - name: Test task
    command: echo Hello
EOF

cat > "$TEMP_DIR/invalid_playbook.yml" <<'EOF'
- hosts: localhost
tasks:
  - name: Test task
    command: echo Hello
    unknown_directive: value
EOF

ANSIBLE_HOME="$TEMP_DIR"
ANSIBLE_LOCAL_TEMP="$TEMP_DIR"
export ANSIBLE_HOME ANSIBLE_LOCAL_TEMP

if "${VENV_DIR}/bin/ansible-playbook" --syntax-check "$TEMP_DIR/playbook.yml" >/dev/null 2>&1; then
echo "Ansible playbook syntax check passed"
else
echo "Ansible playbook syntax check failed unexpectedly"
exit 1
fi

if ! "${VENV_DIR}/bin/ansible-playbook" --syntax-check "$TEMP_DIR/invalid_playbook.yml" >/dev/null 2>&1; then
echo "Ansible invalid playbook syntax check detected as expected"
else
echo "Ansible invalid playbook syntax check not detected"
exit 1
fi

echo "Suite 2 passed"

# Suite 3: Ansible Lint Verification
if [ ! -x "${VENV_DIR}/bin/ansible-lint" ]; then
echo "Ansible-lint binary not found in ${VENV_DIR}/bin/"
exit 1
fi

if "${VENV_DIR}/bin/ansible-lint" --version >/dev/null 2>&1; then
echo "Ansible-lint version check passed"
else
echo "Ansible-lint version check failed"
exit 1
fi

if "${VENV_DIR}/bin/ansible-lint" "$TEMP_DIR/playbook.yml" >/dev/null 2>&1; then
echo "Ansible-lint check passed"
else
echo "Ansible-lint check failed"
exit 1
fi

echo "Suite 3 passed"

# Suite 4: ShellCheck Static Analysis
if [ ! -x "${VENV_DIR}/bin/shellcheck" ]; then
echo "ShellCheck binary not found in ${VENV_DIR}/bin/"
exit 1
fi

if "${VENV_DIR}/bin/shellcheck" --version >/dev/null 2>&1; then
echo "ShellCheck version check passed"
else
echo "ShellCheck version check failed"
exit 1
fi

cat > "$TEMP_DIR/clean_script.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
echo "Clean script"
exit 0
EOF

if "${VENV_DIR}/bin/shellcheck" "$TEMP_DIR/clean_script.sh" >/dev/null 2>&1; then
echo "ShellCheck clean script check passed"
else
echo "ShellCheck clean script check failed"
exit 1
fi

cat > "$TEMP_DIR/flawed_script.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
echo Clean script
exit 0
EOF

if ! "${VENV_DIR}/bin/shellcheck" "$TEMP_DIR/flawed_script.sh" >/dev/null 2>&1; then
echo "ShellCheck flawed script check detected as expected"
else
echo "ShellCheck flawed script check not detected"
exit 1
fi

echo "Suite 4 passed"

echo "🎉 Code Quality & Pre-Flight Linters verification passed!"
