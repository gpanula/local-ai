#!/usr/bin/env bash
# ==============================================================================
# Start Terminal MCP Listener for Local AI & Antigravity
# ==============================================================================
# Exposes an interactive PTY session via Model Context Protocol (MCP)
# with dynamic sandbox boundaries and automatic asciicast session recording.
# ==============================================================================

set -euo pipefail

trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
PROJECT_ROOT_LOGICAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd -L || echo "${PROJECT_ROOT}")"
RECORDINGS_DIR="${PROJECT_ROOT}/recordings"
SANDBOX_TEMPLATE="${SCRIPT_DIR}/terminal_sandbox.json"
GENERATE_SCRIPT="${SCRIPT_DIR}/generate_sandbox_config.py"

# Validate sandbox template integrity
if [[ ! -f "${SANDBOX_TEMPLATE}" ]]; then
  echo "❌ [ERROR] Sandbox template not found: ${SANDBOX_TEMPLATE}" >&2
  exit 1
fi
if [[ -L "${SANDBOX_TEMPLATE}" ]]; then
  echo "❌ [ERROR] Sandbox template is a symlink - refusing to use: ${SANDBOX_TEMPLATE}" >&2
  exit 1
fi
SANDBOX_PERMS=$(stat -c '%a' "${SANDBOX_TEMPLATE}" 2>/dev/null || echo "000")
if [[ "${SANDBOX_PERMS}" =~ [67]$ ]]; then
  echo "❌ [ERROR] Sandbox template is world-writable: ${SANDBOX_TEMPLATE}" >&2
  exit 1
fi

# Ensure recordings directory exists
mkdir -p "${RECORDINGS_DIR}"

# Prepare temporary runtime sandbox configuration
RUNTIME_SANDBOX_DIR="${PROJECT_ROOT}/.git/sandbox_runtime"
mkdir -p "${RUNTIME_SANDBOX_DIR}"
chmod 700 "${RUNTIME_SANDBOX_DIR}" 2>/dev/null || true
RUNTIME_SANDBOX_CONFIG="${RUNTIME_SANDBOX_DIR}/terminal_sandbox_$$.json"

# Dynamically generate runtime sandbox configuration
python3 "${GENERATE_SCRIPT}" \
  --template "${SANDBOX_TEMPLATE}" \
  --output "${RUNTIME_SANDBOX_CONFIG}" \
  --workspace "${PROJECT_ROOT}" \
  --workspace "${PROJECT_ROOT_LOGICAL}" \
  --workspace "$(pwd -L 2>/dev/null || pwd)" \
  --workspace "$(pwd -P 2>/dev/null || pwd)"

echo "================================================================="
echo "  🖥️  Starting Local AI Terminal MCP Listener"
echo "================================================================="
echo "  📁 Workspace (Physical): ${PROJECT_ROOT}"
echo "  📁 Workspace (Logical):  ${PROJECT_ROOT_LOGICAL}"
echo "  🛡️  Sandbox Config:      ${RUNTIME_SANDBOX_CONFIG}"
echo "  🎥 Recordings Dir:       ${RECORDINGS_DIR}"
echo "  ⏱️  Inactivity Limit:     900s (15 min) | Max Duration: 14400s (4 hr)"
echo "================================================================="
echo "  Waiting for Antigravity IDE / Ollama MCP client connection..."
echo "  (Press Ctrl+C to terminate session)"
echo "================================================================="
echo ""

# Clean up temporary sandbox config and 0-byte dummy artifact files left by bwrap / sandbox-runtime
cleanup_sandbox() {
  rm -f "${RUNTIME_SANDBOX_CONFIG}" 2>/dev/null || true
  local target_dirs=("${PROJECT_ROOT}" "${SCRIPT_DIR}")
  for dir in "${target_dirs[@]}"; do
    for artifact in .git .bashrc .bash_profile .zshrc .zprofile .profile .gitconfig .gitmodules .idea .vscode .mcp.json .ripgreprc .claude; do
      local target="${dir}/${artifact}"
      if [[ -f "${target}" && ! -s "${target}" ]]; then
        rm -f "${target}" 2>/dev/null || true
      fi
    done
  done
}

# Ensure cleanup runs on normal exit or interruption
trap cleanup_sandbox EXIT INT TERM

# Always operate from workspace root
cd "${PROJECT_ROOT}"

# Configure prompt for both Bash and Zsh: [⚡ mcp] <userid>:<current_dir>$
# 1. Bash format (using PROMPT_COMMAND with \u and \W)
export PROMPT_COMMAND='PS1="\[\033[30;43m\] ⚡ mcp \[\033[0m\] \[\033[01;32m\]\u\[\033[00m\]:\[\033[01;34m\]\W\[\033[00m\]\$ "'
# 2. Zsh format (macOS default, using PROMPT with %n and %1~)
export PROMPT=$'%{\e[30;43m%} ⚡ mcp %{\e[0m%} %{\e[01;32m%}%n%{\e[00m%}:%{\e[01;34m%}%1~%{\e[00m%}%# '

npx -y github:gpanula/terminal-mcp \
  --sandbox \
  --sandbox-config "${RUNTIME_SANDBOX_CONFIG}" \
  --record always \
  --record-dir "${RECORDINGS_DIR}" \
  --inactivity-timeout 900 \
  --max-duration 14400 \
  "$@"
