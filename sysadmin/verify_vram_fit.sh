#!/bin/bash
# ==============================================================================
# verify_vram_fit.sh — Ollama Model GPU VRAM Residency & Offload Audit
# ==============================================================================
set -euo pipefail

# Diagnostic traps
trap 'echo "❌ [ERROR] Line ${LINENO}: command failed: ${BASH_COMMAND}" >&2; exit 1' ERR

# ------------------------------------------------------------------------------
# 1. Deterministic Environment & Binary Resolution (Rule #1 & Rule #2)
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${VENV_DIR:-${REPO_ROOT}/sysadmin/venv}"
PYTHON_BIN="${VENV_DIR}/bin/python3"

# Assert required binaries exist and are executable
if [ ! -x "/usr/bin/curl" ]; then
    echo "❌ [ERROR] Required host binary '/usr/bin/curl' is missing or not executable." >&2
    exit 1
fi

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "❌ [ERROR] Isolated virtualenv Python '${PYTHON_BIN}' is missing or not executable." >&2
    exit 1
fi

if command -v ollama >/dev/null 2>&1; then
    OLLAMA_CMD="$(command -v ollama)"
elif [ -x "/usr/local/bin/ollama" ]; then
    OLLAMA_CMD="/usr/local/bin/ollama"
elif [ -x "/usr/bin/ollama" ]; then
    OLLAMA_CMD="/usr/bin/ollama"
else
    echo "❌ [ERROR] 'ollama' binary not found on host." >&2
    exit 1
fi

OLLAMA_HOST_URL="${OLLAMA_HOST:-http://localhost:11434}"
if [[ ! "${OLLAMA_HOST_URL}" =~ ^http ]]; then
    OLLAMA_HOST_URL="http://${OLLAMA_HOST_URL}"
fi

# ------------------------------------------------------------------------------
# Argument Parsing & Model Tier Selection
# ------------------------------------------------------------------------------
TIER_SELECTION="24gb"
MODELS_TO_TEST=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tier|-t)
            TIER_SELECTION="$2"
            shift 2
            ;;
        --tier=*)
            TIER_SELECTION="${1#*=}"
            shift 1
            ;;
        --help|-h)
            echo "Usage: $0 [--tier 8gb|24gb|all] [model_name...]"
            echo ""
            echo "Options:"
            echo "  -t, --tier <8gb|24gb|all>  Select model tier to audit (default: 24gb)"
            echo "  model_name                 Audit a specific model (e.g. winter-coder:24gb)"
            exit 0
            ;;
        *)
            # Specific model name provided
            MODELS_TO_TEST+=("$1")
            shift 1
            ;;
    esac
done

if [ "${#MODELS_TO_TEST[@]}" -eq 0 ]; then
    case "${TIER_SELECTION}" in
        8gb|8GB|fast)
            MODELS_TO_TEST=(
                "winter-orchestrator:8gb"
                "winter-coder:8gb"
                "winter-reviewer:8gb"
            )
            ;;
        16gb|16GB)
            MODELS_TO_TEST=(
                "winter-orchestrator:16gb"
                "winter-coder:16gb"
                "winter-reviewer:16gb"
            )
            ;;
        24gb|24GB)
            MODELS_TO_TEST=(
                "winter-orchestrator:24gb"
                "winter-coder:24gb"
                "winter-reviewer:24gb"
            )
            ;;
        all|ALL)
            MODELS_TO_TEST=(
                "winter-orchestrator:8gb"
                "winter-coder:8gb"
                "winter-reviewer:8gb"
                "winter-orchestrator:16gb"
                "winter-coder:16gb"
                "winter-reviewer:16gb"
                "winter-orchestrator:24gb"
                "winter-coder:24gb"
                "winter-reviewer:24gb"
            )
            ;;
        *)
            echo "❌ [ERROR] Unknown tier '${TIER_SELECTION}'. Supported: 8gb, 16gb, 24gb, all" >&2
            exit 1
            ;;
    esac
fi

# shellcheck disable=SC2329
cleanup() {
    echo ""
    echo "🧹 [Cleanup] Unloading test models from VRAM..."
    for m in "${MODELS_TO_TEST[@]}"; do
        curl -s -X POST "${OLLAMA_HOST_URL}/api/generate" \
            -d "{\"model\": \"${m}\", \"keep_alive\": 0}" >/dev/null 2>&1 || true
    done
}
trap cleanup EXIT

echo "=============================================================================="
echo "🔍 GPU VRAM Residency & CPU Offload Audit"
echo "=============================================================================="
echo "  Repo Root:   ${REPO_ROOT}"
echo "  Python:      ${PYTHON_BIN}"
echo "  Ollama Bin:  ${OLLAMA_CMD}"
echo "  Ollama Host: ${OLLAMA_HOST_URL}"
echo "  Models:      ${MODELS_TO_TEST[*]}"
echo "------------------------------------------------------------------------------"

# Query baseline GPU usage (with graceful fallback if running inside container)
HAS_NVIDIA_SMI=0
GPU_NAME="Host GPU (via Ollama API)"
TOTAL_VRAM_MB="24576"
INITIAL_USED_VRAM_MB="N/A"

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    HAS_NVIDIA_SMI=1
    GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader | sed -n '1p')"
    TOTAL_VRAM_MB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | sed -n '1p' | tr -d ' ')"
    INITIAL_USED_VRAM_MB="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sed -n '1p' | tr -d ' ')"
fi

echo "  GPU Device:  ${GPU_NAME}"
echo "  Total VRAM:  ${TOTAL_VRAM_MB} MB"
echo "  Used (Cold): ${INITIAL_USED_VRAM_MB} MB"
echo "=============================================================================="

# ------------------------------------------------------------------------------
# Diagnostic Execution Loop
# ------------------------------------------------------------------------------
AUDIT_FAILED=0

for target_model in "${MODELS_TO_TEST[@]}"; do
    echo ""
    echo "▶️ Testing model: ${target_model}"

    # 1. Unload other models to test single-model residency
    for m in "${MODELS_TO_TEST[@]}"; do
        curl -s -X POST "${OLLAMA_HOST_URL}/api/generate" \
            -d "{\"model\": \"${m}\", \"keep_alive\": 0}" >/dev/null 2>&1 || true
    done
    sleep 1

    # 2. Warm up model by issuing a test prompt to measure generation speed and allocate context
    WARMUP_START="$(date +%s%N)"
    WARMUP_RESP="$(curl -s -X POST "${OLLAMA_HOST_URL}/api/generate" \
        -d "{\"model\": \"${target_model}\", \"prompt\": \"Write a short 3-line bash script that prints hello.\", \"stream\": false, \"keep_alive\": \"5m\"}")"
    WARMUP_END="$(date +%s%N)"
    WARMUP_MS="$(( (WARMUP_END - WARMUP_START) / 1000000 ))"

    if [ -z "${WARMUP_RESP}" ] || echo "${WARMUP_RESP}" | grep -q '"error"'; then
        echo "❌ [ERROR] Failed to warm up model '${target_model}': ${WARMUP_RESP}" >&2
        AUDIT_FAILED=1
        continue
    fi

    # 3. Query /api/ps and analyze VRAM residency
    PS_RESP="$(curl -s "${OLLAMA_HOST_URL}/api/ps")"
    if [ "${HAS_NVIDIA_SMI}" -eq 1 ]; then
        CURRENT_USED_VRAM_MB="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sed -n '1p' | tr -d ' ')"
        FREE_VRAM_MB="$(( TOTAL_VRAM_MB - CURRENT_USED_VRAM_MB ))"
    else
        FREE_VRAM_MB="-1"
    fi

    # Evaluate metrics via Python helper
    METRICS_JSON="$("${PYTHON_BIN}" - "${target_model}" "${PS_RESP}" "${TOTAL_VRAM_MB}" "${FREE_VRAM_MB}" "${WARMUP_RESP}" "${WARMUP_MS}" <<'PYEOF'
import sys
import json

target_model = sys.argv[1]
raw_ps = sys.argv[2]
total_vram = int(sys.argv[3])
free_vram = int(sys.argv[4])
raw_warmup = sys.argv[5]
warmup_ms = int(sys.argv[6])

try:
    ps_data = json.loads(raw_ps)
except Exception:
    ps_data = {"models": []}

try:
    warmup_data = json.loads(raw_warmup)
except Exception:
    warmup_data = {}

eval_count = warmup_data.get("eval_count", 0)
eval_duration_ns = warmup_data.get("eval_duration", 0)
eval_sec = (eval_duration_ns / 1e9) if eval_duration_ns > 0 else (warmup_ms / 1000.0)
tps = (eval_count / eval_sec) if eval_sec > 0 else 0.0

if tps < 26.0:
    tps_str = f"🚨 {tps:.1f} t/s (CRITICAL LOW)"
elif tps < 51.0:
    tps_str = f"⚠️ {tps:.1f} t/s"
else:
    tps_str = f"{tps:.1f} t/s"

model_info = None
for m in ps_data.get("models", []):
    if m.get("name") == target_model or m.get("model") == target_model:
        model_info = m
        break

if not model_info:
    result = {
        "found": False,
        "error": f"Model '{target_model}' not found in active /api/ps list"
    }
else:
    size_bytes = model_info.get("size", 0)
    size_vram_bytes = model_info.get("size_vram", 0)
    context_length = model_info.get("context_length", 0)
    
    size_mb = size_bytes / (1024 * 1024)
    size_vram_mb = size_vram_bytes / (1024 * 1024)
    spill_mb = max(0, size_mb - size_vram_mb)
    offload_pct = (spill_mb / size_mb * 100) if size_mb > 0 else 0.0
    
    if size_vram_bytes >= size_bytes:
        processor = "100% GPU"
    elif size_vram_bytes == 0:
        processor = "100% CPU"
    else:
        gpu_pct = (size_vram_bytes / size_bytes) * 100
        cpu_pct = 100.0 - gpu_pct
        processor = f"{gpu_pct:.1f}% GPU / {cpu_pct:.1f}% CPU"

    computed_free = free_vram if free_vram >= 0 else max(0, int(total_vram - size_vram_mb))

    result = {
        "found": True,
        "size_mb": round(size_mb, 1),
        "size_vram_mb": round(size_vram_mb, 1),
        "spill_mb": round(spill_mb, 1),
        "offload_pct": round(offload_pct, 1),
        "context_length": context_length,
        "processor": processor,
        "free_vram_mb": computed_free,
        "tps_str": tps_str,
        "eval_count": eval_count,
        "eval_sec": round(eval_sec, 2),
        "fits_100_percent": (spill_mb == 0 and size_vram_bytes > 0)
    }

print(json.dumps(result))
PYEOF
)"

    IS_FOUND="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''').get('found', False))")"
    if [ "${IS_FOUND}" != "True" ]; then
        echo "⚠️ [WARNING] Model status could not be verified in /api/ps."
        AUDIT_FAILED=1
        continue
    fi

    # Read extracted values
    SIZE_MB="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['size_mb'])")"
    SIZE_VRAM_MB="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['size_vram_mb'])")"
    SPILL_MB="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['spill_mb'])")"
    OFFLOAD_PCT="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['offload_pct'])")"
    CONTEXT_LEN="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['context_length'])")"
    PROCESSOR="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['processor'])")"
    TPS_STR="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['tps_str'])")"
    EVAL_COUNT="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['eval_count'])")"
    EVAL_SEC="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['eval_sec'])")"
    COMP_FREE="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['free_vram_mb'])")"
    FITS_100="$("${PYTHON_BIN}" -c "import json; print(json.loads('''${METRICS_JSON}''')['fits_100_percent'])")"

    # Display comprehensive diagnostic summary with t/s telemetry
    echo "  📊 Model: ${target_model} | Context: ${CONTEXT_LEN} tokens | Speed: ${TPS_STR} (${EVAL_COUNT} tokens in ${EVAL_SEC}s)"
    echo "     Processor: ${PROCESSOR} | VRAM: ${SIZE_VRAM_MB} MB / Total: ${SIZE_MB} MB | Free GPU: ${COMP_FREE} MB"

    if [ "${FITS_100}" = "True" ]; then
        echo "  ✅ [100% GPU VRAM] Model '${target_model}' fits entirely in VRAM with zero CPU offload."
    else
        echo "  🚨 [CPU OFFLOAD DETECTED] Model '${target_model}' spilled ${SPILL_MB} MB (${OFFLOAD_PCT}%) into System RAM!"
        AUDIT_FAILED=1
    fi
done

# ------------------------------------------------------------------------------
# Final Exit Gate
# ------------------------------------------------------------------------------
echo ""
echo "=============================================================================="
if [ "${AUDIT_FAILED}" -eq 0 ]; then
    echo "🎉 All tested models fit 100% in GPU VRAM with zero CPU offloading!"
    echo "=============================================================================="
    exit 0
else
    echo "❌ [FAILURE] One or more models offloaded layers or KV-cache to System RAM."
    echo "=============================================================================="
    exit 1
fi
