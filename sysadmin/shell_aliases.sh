# ==============================================================================
# Local AI Project Shell Aliases & Helper Functions (Bash & Zsh Compatible)
# ==============================================================================
# Supports: Linux (Bash/Zsh) and macOS (Zsh/Bash)
#
# Usage:
#   Bash (Linux/macOS):
#     source <path-to-repo>/sysadmin/shell_aliases.sh
#
#   Zsh (macOS default & Linux):
#     source <path-to-repo>/sysadmin/shell_aliases.sh
# ==============================================================================

# Dynamically determine the root directory of this repository
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  _LOCALAI_ALIAS_SRC="${BASH_SOURCE[0]}"
elif [[ -n "${ZSH_VERSION:-}" ]]; then
  _LOCALAI_ALIAS_SRC="${(%):-%x}"
else
  _LOCALAI_ALIAS_SRC="${0:-}"
fi

if [[ -n "${_LOCALAI_ALIAS_SRC}" && -f "${_LOCALAI_ALIAS_SRC}" ]]; then
  _LOCALAI_SCRIPT_DIR="$(cd "$(dirname "${_LOCALAI_ALIAS_SRC}")" && pwd -P)"
  LOCAL_AI_DIR="$(cd "${_LOCALAI_SCRIPT_DIR}/.." && pwd -P)"
else
  LOCAL_AI_DIR="${LOCAL_AI_DIR:-${HOME}/Projects/local-ai}"
fi

# Start Sandboxed Terminal MCP with Session Recording
alias localai-term="${LOCAL_AI_DIR}/sysadmin/start_terminal_mcp.sh"

# Start Unrestricted Terminal MCP with Session Recording
alias localai-term-raw="npx -y github:gpanula/terminal-mcp --record always --record-dir ${LOCAL_AI_DIR}/recordings --inactivity-timeout 900 --max-duration 14400"

# List all recorded session casts
alias localai-recordings="ls -laht ${LOCAL_AI_DIR}/recordings"

# Replay the most recent terminal recording session
localai-replay-latest() {
  local latest_cast
  latest_cast=$(ls -t "${LOCAL_AI_DIR}/recordings"/*.cast 2>/dev/null | head -n 1)
  if [[ -n "${latest_cast}" && -f "${latest_cast}" ]]; then
    echo "▶️  Replaying latest recording: ${latest_cast}"
    asciinema play "${latest_cast}"
  else
    echo "⚠️  No .cast recordings found in ${LOCAL_AI_DIR}/recordings/"
  fi
}

# Replay a specific recording by name or path
localai-replay() {
  if [[ -z "${1:-}" ]]; then
    echo "Usage: localai-replay <recording.cast>"
    return 1
  fi
  asciinema play "$1"
}

# Inspect local Ollama models
alias localai-models="curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool"

# Cross-Platform GPU / Hardware status (NVIDIA on Linux, Metal / Apple Silicon on macOS)
localai-gpu() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi "$@"
  elif [[ "${OSTYPE:-}" == "darwin"* ]]; then
    echo "🍏 macOS Detected: Querying Display / Metal hardware..."
    system_profiler SPDisplaysDataType
  else
    echo "⚠️  No nvidia-smi or macOS display profiler detected."
  fi
}

# View current Antigravity MCP server configuration
alias localai-mcp-config="cat ~/.gemini/config/mcp_config.json | python3 -m json.tool"

# AI Memory & Lessons Management
alias localai-lessons="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py review-lessons"
alias localai-lessons-auto="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py review-lessons --auto"
alias localai-audit="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py audit-lessons"
alias localai-wiki="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py compile-wiki"
alias localai-compact="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py compact-lessons"
alias localai-compact-auto="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py compact-lessons --auto"
alias localai-compact-queue="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py compact-lessons --queue-only"
alias localai-compact-active="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py compact-lessons --active-only"

# Ollama Model & Pipeline Management
alias localai-unload="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py unload-model"
alias localai-pipeline="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py pipeline-run"
alias localai-pipeline-8gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py pipeline-run --tier 8gb --keep-models"
alias localai-pipeline-16gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py pipeline-run --tier 16gb --unload-models"
alias localai-pipeline-24gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py pipeline-run --tier 24gb --unload-models"
alias localai-build-models="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py build-models"
alias localai-build-models-8gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py build-models 8gb"
alias localai-build-models-16gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py build-models 16gb"
alias localai-build-models-24gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py build-models 24gb"

# Model Diagnostic & VRAM Verification
alias localai-verify-vram="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py verify-vram"
alias localai-verify-vram-8gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py verify-vram --tier 8gb"
alias localai-verify-vram-16gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py verify-vram --tier 16gb"
alias localai-verify-vram-24gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py verify-vram --tier 24gb"

# Dataset Export & Fine-Tuning
alias localai-export-dataset="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py export-dataset"
alias localai-train="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py train"
alias localai-train-8gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py train --tier 8gb"
alias localai-train-16gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py train --tier 16gb"
alias localai-train-24gb="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py train --tier 24gb"
alias localai-train-dpo="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py train --method dpo"
alias localai-train-sft="python3 ${LOCAL_AI_DIR}/sysadmin/mcp_client.py train --method sft"
