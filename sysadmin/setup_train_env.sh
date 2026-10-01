#!/bin/bash
# ==============================================================================
# Setup Isolated Fine-Tuning Environment (train_venv)
# ==============================================================================
# Installs PyTorch (CUDA 12), Transformers, TRL, PEFT, Datasets, Accelerate,
# and BitsAndBytes in an isolated virtual environment for local model training.
# ==============================================================================

set -euo pipefail
trap 'echo "❌ [ERROR] Line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TRAIN_VENV_DIR="${1:-${REPO_ROOT}/sysadmin/train_venv}"

echo "=============================================================================="
echo "🚀 Initializing Isolated Training Environment: ${TRAIN_VENV_DIR}"
echo "=============================================================================="

# 1. Assert host python3 is available
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ [ERROR] System 'python3' binary not found." >&2
    exit 1
fi

# 2. Create virtual environment if missing
if [ ! -d "${TRAIN_VENV_DIR}" ]; then
    echo "📦 Creating virtual environment at ${TRAIN_VENV_DIR}..."
    python3 -m venv "${TRAIN_VENV_DIR}"
fi

TRAIN_PYTHON="${TRAIN_VENV_DIR}/bin/python3"
TRAIN_PIP="${TRAIN_VENV_DIR}/bin/pip"

if [ ! -x "${TRAIN_PYTHON}" ] || [ ! -x "${TRAIN_PIP}" ]; then
    echo "❌ [ERROR] Failed to initialize virtualenv binaries in ${TRAIN_VENV_DIR}" >&2
    exit 1
fi

# 3. Upgrade pip and build tools
echo "⬆️  Upgrading pip, setuptools, wheel..."
"${TRAIN_PIP}" install --quiet --upgrade pip setuptools wheel

# 4. Install PyTorch with CUDA 12 support
echo "🔥 Installing PyTorch with CUDA 12 runtime..."
"${TRAIN_PIP}" install --quiet torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 || \
"${TRAIN_PIP}" install --quiet torch torchvision torchaudio

# 5. Install Hugging Face training stack
echo "📚 Installing Transformers, TRL, PEFT, BitsAndBytes, Datasets, Accelerate..."
"${TRAIN_PIP}" install --quiet \
    transformers \
    trl \
    peft \
    bitsandbytes \
    accelerate \
    datasets \
    scipy \
    sentencepiece

# 6. Verify CUDA availability and environment
echo "🔍 Verifying CUDA GPU acceleration in train_venv..."
"${TRAIN_PYTHON}" - <<'PYEOF'
import torch
print(f"  PyTorch Version: {torch.__version__}")
print(f"  CUDA Available:  {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  Device Name:     {torch.cuda.get_device_name(0)}")
    print(f"  VRAM Total:      {torch.cuda.get_device_properties(0).total_memory / (1024**3):.2f} GB")
else:
    print("  ⚠️ CUDA not detected by PyTorch!")
PYEOF

echo "=============================================================================="
echo "🎉 Training environment successfully provisioned at: ${TRAIN_VENV_DIR}"
echo "=============================================================================="
