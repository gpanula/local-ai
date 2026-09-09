#!/bin/bash
set -euo pipefail

# Resolve repository root and virtual environment path
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"

# Define required binaries
REQUIRED_BINARIES=("python" "pip" "ansible" "ansible-playbook" "ansible-lint" "shellcheck")

# Function to check binary existence and executability
check_binary() {
    local binary="$1"
    if [ ! -x "${VENV_DIR}/bin/${binary}" ]; then
        echo "Error: ${binary} not found or not executable in ${VENV_DIR}/bin"
        exit 1
    fi
}

# Check all required binaries
for binary in "${REQUIRED_BINARIES[@]}"; do
    check_binary "$binary"
done

# Define temporary directory for test files
TEMP_DIR="/tmp/verify_code_quality_toolchain_$$"
mkdir -p "$TEMP_DIR"

# Cleanup function
cleanup() {
    rm -rf "$TEMP_DIR"
}

# Install EXIT trap for cleanup
trap cleanup EXIT

# ERR trap to print failed command and line number
trap 'echo "Error on line $LINENO: $BASH_COMMAND" >&2' ERR

# Suite 1: Python AST & PyYAML In-Memory Validation
echo "Running Suite 1: Python AST & PyYAML In-Memory Validation"
"${VENV_DIR}/bin/python" -c "import ast; ast.parse('def foo(): pass')"
"${VENV_DIR}/bin/python" -c "import yaml; yaml.safe_load('key: value')"
if ! "${VENV_DIR}/bin/python" -c "import ast; ast.parse('def foo(:')"; then
    echo "Suite 1: Invalid Python syntax correctly detected"
else
    echo "Suite 1: Invalid Python syntax not detected"
    exit 1
fi
if ! "${VENV_DIR}/bin/python" -c "import yaml; yaml.safe_load('key: value:')"; then
    echo "Suite 1: Invalid YAML structure correctly detected"
else
    echo "Suite 1: Invalid YAML structure not detected"
    exit 1
fi

# Suite 2: Ansible Syntax Check & Sandbox Isolation
echo "Running Suite 2: Ansible Syntax Check & Sandbox Isolation"
cat > "$TEMP_DIR/valid_playbook.yml" <<'EOF'
---
- name: Test Playbook
  hosts: localhost
  tasks:
    - name: Ping localhost
      ansible.builtin.ping:
EOF
"${VENV_DIR}/bin/ansible-playbook" --syntax-check "$TEMP_DIR/valid_playbook.yml"
cat > "$TEMP_DIR/invalid_playbook.yml" <<'EOF'
---
- name: Test Playbook
  hosts: localhost
  tasks:
    - name: Ping localhost
      ansible.builtin.ping
EOF
if ! "${VENV_DIR}/bin/ansible-playbook" --syntax-check "$TEMP_DIR/invalid_playbook.yml"; then
    echo "Suite 2: Invalid playbook syntax correctly detected"
else
    echo "Suite 2: Invalid playbook syntax not detected"
    exit 1
fi

# Suite 3: Ansible Lint Verification
echo "Running Suite 3: Ansible Lint Verification"
"${VENV_DIR}/bin/ansible-lint" --version
"${VENV_DIR}/bin/ansible-lint" "$TEMP_DIR/valid_playbook.yml"

# Suite 4: ShellCheck Static Analysis
echo "Running Suite 4: ShellCheck Static Analysis"
"${VENV_DIR}/bin/shellcheck" --version
cat > "$TEMP_DIR/clean_script.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
echo "Clean script"
EOF
"${VENV_DIR}/bin/shellcheck" "$TEMP_DIR/clean_script.sh"
cat > "$TEMP_DIR/flawed_script.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
echo $var
EOF
if ! "${VENV_DIR}/bin/shellcheck" "$TEMP_DIR/flawed_script.sh"; then
    echo "Suite 4: Flawed script correctly detected"
else
    echo "Suite 4: Flawed script not detected"
    exit 1
fi

echo "🎉 Code Quality & Pre-Flight Linters verification passed!"