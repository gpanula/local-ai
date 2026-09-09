# Universal System Rules

> **Purpose**: Curated defensive engineering invariants promoted from recurring lessons
> via the `audit-lessons` process. Both the Author and Reviewer load this file at the
> start of every pipeline run.
>
> **Format**: Each rule is a numbered block with provenance metadata:
>
> ```markdown
> ### Rule #N: <Title>
> **Promoted**: <date> | **Source Lessons**: <lesson-id-1>, <lesson-id-2>
>
> <rule text>
> ```

<!-- Rules are appended below this line by the audit-lessons promotion flow. -->

### Rule #1: Deterministic Virtual Environment & Binary Isolation
**Promoted**: 2026-08-30 | **Source Lessons**: lesson-20260830-01

Never assume `$PATH` or hardcode local relative `venv/` paths. All scripts must deterministically resolve the repository root and the virtual environment path defaulting to `${REPO_ROOT}/sysadmin/venv`:
```bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="${1:-${REPO_ROOT}/sysadmin/venv}"
```
All binaries must be invoked via explicit paths (`"${VENV_DIR}/bin/<binary>"`), and assert existence (`[ -x "${VENV_DIR}/bin/<binary>" ]`) before proceeding.

### Rule #2: Ansible Playbook Standards for Pre-Flight Linting
**Promoted**: 2026-08-30 | **Source Lessons**: lesson-20260830-02

In Ansible playbooks and test fixtures:
1. Always give every task an explicit descriptive name (`- name: <task description>`) to satisfy `ansible-lint` `name[missing]` rules.
2. Always use Fully Qualified Collection Names (FQCN) with a trailing colon mapping for module actions (e.g. `ansible.builtin.ping:`, `ansible.builtin.debug:`, `ansible.builtin.command:`) to ensure valid YAML structure and satisfy `ansible-lint` `fqcn[action-core]` rules. Example:
```yaml
---
- name: Test Playbook
  hosts: localhost
  tasks:
    - name: Ping localhost
      ansible.builtin.ping:
```

### Rule #3: Negative Test Fixture Design
**Promoted**: 2026-08-30 | **Source Lessons**: lesson-20260830-03

When constructing test fixtures for syntax checkers or linters:
1. Always write test fixture files using single-line strings (`"def foo(): pass"`, `"key: value"`) or heredocs (`cat > "$file" <<'EOF'`) rather than `printf "%s" "...\n..."` to prevent literal backslash injection into code files.
2. Ensure negative test fixtures contain genuinely malformed syntax that causes the tool to fail with a non-zero exit code:
   - Python AST: `def foo(:` (unclosed syntax -> non-zero exit)
   - PyYAML: `key: value:` (malformed mapping / duplicate colon -> non-zero exit)
   - Ansible Playbook: conflicting action keys or bad indentation -> non-zero exit
   - ShellCheck: `#!/bin/bash\necho "unclosed` (unclosed quote syntax error -> non-zero exit). Note: subtle style warnings like `echo $var` may not trigger non-zero exit without flags; use an actual syntax error like unclosed quotes to guarantee a non-zero exit code. Always quote EOF when creating shell scripts with heredocs (`cat > invalid_script.sh <<'EOF'`) to avoid premature variable expansion.
