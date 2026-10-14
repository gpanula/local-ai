#!/usr/bin/env bash
# ==============================================================================
# Build Script for Winter Customized Ollama Models
# ==============================================================================
# Builds 6 specialized roles (orchestrator, architect, coder, sysadmin, security, reviewer)
# across 3 hardware tiers (8gb, 16gb, 24gb).
#
# Usage:
#   ./build_models.sh [8gb | 16gb | 24gb | all | pull-8gb | pull-16gb | pull-24gb | pull-all | list]
# ==============================================================================

set -euo pipefail
trap 'echo "❌ [ERROR] Line ${LINENO}: ${BASH_COMMAND}" >&2; exit 1' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

pull_8gb() {
    echo "📥 [Pre-pulling Base Models for 8GB Tier]"
    ollama pull qwen2.5-coder:7b
    ollama pull qwen3:8b
    ollama pull deepseek-r1:8b
    echo "✅ 8GB base models pulled successfully!"
}

pull_16gb() {
    echo "📥 [Pre-pulling Base Models for 16GB Tier]"
    ollama pull qwen2.5-coder:14b
    ollama pull deepseek-coder-v2:16b
    echo "✅ 16GB base models pulled successfully!"
}

pull_24gb() {
    echo "📥 [Pre-pulling Base Models for 24GB Tier]"
    ollama pull qwen2.5-coder:32b
    ollama pull codestral:latest
    echo "✅ 24GB base models pulled successfully!"
}

pull_all() {
    pull_8gb
    pull_16gb
    pull_24gb
    echo "✅ All base models pulled successfully!"
}

build_model() {
    local tier_dir="$1"
    local modelfile="$2"
    local variant_tag="$3"
    local alias_tag="$4"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔨 Building ${variant_tag} (from ${tier_dir}/${modelfile})..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    (cd "${SCRIPT_DIR}/${tier_dir}" && ollama create "${variant_tag}" -f "${modelfile}")
    
    if [[ -n "${alias_tag}" && "${alias_tag}" != "${variant_tag}" ]]; then
        echo "🏷️  Aliasing ${variant_tag} -> ${alias_tag}..."
        ollama cp "${variant_tag}" "${alias_tag}"
    fi
    echo "✅ Successfully built and tagged ${variant_tag}"
    echo ""
}

build_8gb() {
    echo "🟢 [Building 8GB VRAM Tier Models] (Target: ~5.0 - 6.5 GB VRAM)"
    build_model "8gb" "Modelfile-orchestrator-deepseek8b" "winter-orchestrator:8gb-deepseek" "winter-orchestrator:8gb"
    build_model "8gb" "Modelfile-architect-qwen7b"        "winter-architect:8gb-qwen"        "winter-architect:8gb"
    build_model "8gb" "Modelfile-coder-qwen7b"            "winter-coder:8gb-qwen"            "winter-coder:8gb"
    build_model "8gb" "Modelfile-coder-deepseek8b"        "winter-coder:8gb-deepseek"        "winter-coder:8gb-deepseek"
    build_model "8gb" "Modelfile-sysadmin-qwen7b"         "winter-sysadmin:8gb-qwen"         "winter-sysadmin:8gb"
    build_model "8gb" "Modelfile-security-deepseek8b"     "winter-security:8gb-deepseek"     "winter-security:8gb"
    build_model "8gb" "Modelfile-reviewer-qwen8b"         "winter-reviewer:8gb-qwen"         "winter-reviewer:8gb"
    echo "🎉 All 8GB tier models built successfully!"
}

build_16gb() {
    echo "🟡 [Building 16GB VRAM Tier Models] (Target: ~10 - 14 GB VRAM)"
    build_model "16gb" "Modelfile-orchestrator-deepseek16b" "winter-orchestrator:16gb-deepseek" "winter-orchestrator:16gb"
    build_model "16gb" "Modelfile-architect-deepseek16b"    "winter-architect:16gb-deepseek"    "winter-architect:16gb"
    build_model "16gb" "Modelfile-coder-qwen14b"            "winter-coder:16gb-qwen"            "winter-coder:16gb"
    build_model "16gb" "Modelfile-coder-deepseek16b"        "winter-coder:16gb-deepseek"        "winter-coder:16gb-deepseek"
    build_model "16gb" "Modelfile-sysadmin-qwen14b"         "winter-sysadmin:16gb-qwen"         "winter-sysadmin:16gb"
    build_model "16gb" "Modelfile-security-deepseek16b"     "winter-security:16gb-deepseek"     "winter-security:16gb"
    build_model "16gb" "Modelfile-reviewer-deepseek16b"     "winter-reviewer:16gb-deepseek"     "winter-reviewer:16gb"
    echo "🎉 All 16GB tier models built successfully!"
}

build_24gb() {
    echo "🟣 [Building 24GB VRAM Tier Models] (Target: ~16 - 22 GB VRAM)"
    build_model "24gb" "Modelfile-orchestrator-qwen32b"   "winter-orchestrator:24gb-qwen"   "winter-orchestrator:24gb"
    build_model "24gb" "Modelfile-architect-qwen32b"      "winter-architect:24gb-qwen"      "winter-architect:24gb"
    build_model "24gb" "Modelfile-coder-qwen32b"          "winter-coder:24gb-qwen"          "winter-coder:24gb"
    build_model "24gb" "Modelfile-coder-codestral"        "winter-coder:24gb-codestral"     "winter-coder:24gb-codestral"
    build_model "24gb" "Modelfile-coder-deepseek16b"      "winter-coder:24gb-deepseek"      "winter-coder:24gb-deepseek"
    build_model "24gb" "Modelfile-sysadmin-codestral"     "winter-sysadmin:24gb-codestral"  "winter-sysadmin:24gb"
    build_model "24gb" "Modelfile-security-codestral"     "winter-security:24gb-codestral"  "winter-security:24gb"
    build_model "24gb" "Modelfile-reviewer-codestral"     "winter-reviewer:24gb-codestral"  "winter-reviewer:24gb"
    echo "🎉 All 24GB tier models built successfully!"
}

build_prime_8gb() {
    echo "🟢 [Building 8GB Prime Model] (Target: ~5.0 - 6.5 GB VRAM)"
    build_model "8gb" "Modelfile-prime-qwen7b" "winter-prime:8gb-qwen" "winter-prime:8gb"
    echo "🏷️  Aliasing winter-prime:8gb -> winter-prime:latest..."
    ollama cp "winter-prime:8gb" "winter-prime:latest" || true
    echo "🎉 8GB Prime model built successfully!"
}

build_prime_16gb() {
    echo "🟡 [Building 16GB Prime Model] (Target: ~10 - 14 GB VRAM)"
    build_model "16gb" "Modelfile-prime-qwen14b" "winter-prime:16gb-qwen" "winter-prime:16gb"
    echo "🎉 16GB Prime model built successfully!"
}

build_prime_24gb() {
    echo "🟣 [Building 24GB Prime Model] (Target: ~16 - 22 GB VRAM)"
    build_model "24gb" "Modelfile-prime-qwen32b" "winter-prime:24gb-qwen" "winter-prime:24gb"
    echo "🎉 24GB Prime model built successfully!"
}

build_prime() {
    build_prime_8gb
    build_prime_16gb
    build_prime_24gb
    echo "🎉 All Prime models built successfully!"
}

build_by_file() {
    local target="$1"
    local filename="$(basename "${target}")"
    local tier_dir=""

    if [[ "${target}" == *"8gb"* ]]; then
        tier_dir="8gb"
    elif [[ "${target}" == *"16gb"* ]]; then
        tier_dir="16gb"
    elif [[ "${target}" == *"24gb"* ]]; then
        tier_dir="24gb"
    else
        if [[ -f "${SCRIPT_DIR}/8gb/${filename}" ]]; then
            tier_dir="8gb"
        elif [[ -f "${SCRIPT_DIR}/16gb/${filename}" ]]; then
            tier_dir="16gb"
        elif [[ -f "${SCRIPT_DIR}/24gb/${filename}" ]]; then
            tier_dir="24gb"
        fi
    fi

    case "${tier_dir}/${filename}" in
        8gb/Modelfile-orchestrator-deepseek8b)
            build_model "8gb" "${filename}" "winter-orchestrator:8gb-deepseek" "winter-orchestrator:8gb" ;;
        8gb/Modelfile-architect-qwen7b)
            build_model "8gb" "${filename}" "winter-architect:8gb-qwen" "winter-architect:8gb" ;;
        8gb/Modelfile-coder-qwen7b)
            build_model "8gb" "${filename}" "winter-coder:8gb-qwen" "winter-coder:8gb" ;;
        8gb/Modelfile-coder-deepseek8b)
            build_model "8gb" "${filename}" "winter-coder:8gb-deepseek" "winter-coder:8gb-deepseek" ;;
        8gb/Modelfile-sysadmin-qwen7b)
            build_model "8gb" "${filename}" "winter-sysadmin:8gb-qwen" "winter-sysadmin:8gb" ;;
        8gb/Modelfile-security-deepseek8b)
            build_model "8gb" "${filename}" "winter-security:8gb-deepseek" "winter-security:8gb" ;;
        8gb/Modelfile-reviewer-qwen8b)
            build_model "8gb" "${filename}" "winter-reviewer:8gb-qwen" "winter-reviewer:8gb" ;;
        8gb/Modelfile-coder-trained)
            build_model "8gb" "${filename}" "winter-coder:8gb-trained" "" ;;
        8gb/Modelfile-prime-qwen7b)
            build_prime_8gb ;;

        16gb/Modelfile-orchestrator-deepseek16b)
            build_model "16gb" "${filename}" "winter-orchestrator:16gb-deepseek" "winter-orchestrator:16gb" ;;
        16gb/Modelfile-architect-deepseek16b)
            build_model "16gb" "${filename}" "winter-architect:16gb-deepseek" "winter-architect:16gb" ;;
        16gb/Modelfile-coder-qwen14b)
            build_model "16gb" "${filename}" "winter-coder:16gb-qwen" "winter-coder:16gb" ;;
        16gb/Modelfile-coder-deepseek16b)
            build_model "16gb" "${filename}" "winter-coder:16gb-deepseek" "winter-coder:16gb-deepseek" ;;
        16gb/Modelfile-sysadmin-qwen14b)
            build_model "16gb" "${filename}" "winter-sysadmin:16gb-qwen" "winter-sysadmin:16gb" ;;
        16gb/Modelfile-security-deepseek16b)
            build_model "16gb" "${filename}" "winter-security:16gb-deepseek" "winter-security:16gb" ;;
        16gb/Modelfile-reviewer-deepseek16b)
            build_model "16gb" "${filename}" "winter-reviewer:16gb-deepseek" "winter-reviewer:16gb" ;;
        16gb/Modelfile-prime-qwen14b)
            build_prime_16gb ;;

        24gb/Modelfile-orchestrator-qwen32b)
            build_model "24gb" "${filename}" "winter-orchestrator:24gb-qwen" "winter-orchestrator:24gb" ;;
        24gb/Modelfile-architect-qwen32b)
            build_model "24gb" "${filename}" "winter-architect:24gb-qwen" "winter-architect:24gb" ;;
        24gb/Modelfile-coder-qwen32b)
            build_model "24gb" "${filename}" "winter-coder:24gb-qwen" "winter-coder:24gb" ;;
        24gb/Modelfile-coder-codestral)
            build_model "24gb" "${filename}" "winter-coder:24gb-codestral" "winter-coder:24gb-codestral" ;;
        24gb/Modelfile-coder-deepseek16b)
            build_model "24gb" "${filename}" "winter-coder:24gb-deepseek" "winter-coder:24gb-deepseek" ;;
        24gb/Modelfile-sysadmin-codestral)
            build_model "24gb" "${filename}" "winter-sysadmin:24gb-codestral" "winter-sysadmin:24gb" ;;
        24gb/Modelfile-security-codestral)
            build_model "24gb" "${filename}" "winter-security:24gb-codestral" "winter-security:24gb" ;;
        24gb/Modelfile-reviewer-codestral)
            build_model "24gb" "${filename}" "winter-reviewer:24gb-codestral" "winter-reviewer:24gb" ;;
        24gb/Modelfile-prime-qwen32b)
            build_prime_24gb ;;

        *)
            echo "⚠️ [WARNING] Unknown or unmapped modelfile: ${target}"
            return 1
            ;;
    esac
}

build_updated() {
    echo "🔍 [Detecting Modified Modelfiles via git...]"
    local repo_root="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
    local modified_files
    modified_files="$(git -C "${repo_root}" status --porcelain | awk '{print $2}' | grep -E 'Modelfile' || true)"
    
    if [[ -z "${modified_files}" ]]; then
        modified_files="$(git -C "${repo_root}" diff --name-only HEAD | grep -E 'Modelfile' || true)"
    fi

    if [[ -z "${modified_files}" ]]; then
        echo "ℹ️  No modified Modelfiles detected."
        return 0
    fi

    echo "Found modified Modelfiles:"
    echo "${modified_files}"
    echo ""

    local count=0
    for f in ${modified_files}; do
        if [[ -f "${repo_root}/${f}" ]] && [[ "${f}" == *"ollama_update/customized_models"* ]]; then
            build_by_file "${f}"
            count=$((count + 1))
        fi
    done
    echo "🎉 Successfully rebuilt ${count} modified model(s)!"
}

list_models() {
    echo "Winter Multi-Agent Model Matrix (6 Roles x 3 Tiers):"
    echo ""
    echo "🟢 8GB Tier (8gb/):"
    echo "  • winter-orchestrator:8gb-deepseek (alias: winter-orchestrator:8gb)"
    echo "  • winter-architect:8gb-qwen        (alias: winter-architect:8gb)"
    echo "  • winter-coder:8gb-qwen            (alias: winter-coder:8gb)"
    echo "  • winter-sysadmin:8gb-qwen         (alias: winter-sysadmin:8gb)"
    echo "  • winter-security:8gb-deepseek     (alias: winter-security:8gb)"
    echo "  • winter-reviewer:8gb-qwen         (alias: winter-reviewer:8gb)"
    echo ""
    echo "🟡 16GB Tier (16gb/):"
    echo "  • winter-orchestrator:16gb-deepseek (alias: winter-orchestrator:16gb)"
    echo "  • winter-architect:16gb-deepseek    (alias: winter-architect:16gb)"
    echo "  • winter-coder:16gb-qwen            (alias: winter-coder:16gb)"
    echo "  • winter-sysadmin:16gb-qwen         (alias: winter-sysadmin:16gb)"
    echo "  • winter-security:16gb-deepseek     (alias: winter-security:16gb)"
    echo "  • winter-reviewer:16gb-deepseek     (alias: winter-reviewer:16gb)"
    echo ""
    echo "🟣 24GB Tier (24gb/):"
    echo "  • winter-orchestrator:24gb-qwen   (alias: winter-orchestrator:24gb)"
    echo "  • winter-architect:24gb-qwen      (alias: winter-architect:24gb)"
    echo "  • winter-coder:24gb-qwen          (alias: winter-coder:24gb)"
    echo "  • winter-coder:24gb-codestral     (alias: winter-coder:24gb-codestral)"
    echo "  • winter-coder:24gb-deepseek      (alias: winter-coder:24gb-deepseek)"
    echo "  • winter-sysadmin:24gb-codestral  (alias: winter-sysadmin:24gb)"
    echo "  • winter-security:24gb-codestral  (alias: winter-security:24gb)"
    echo "  • winter-reviewer:24gb-codestral  (alias: winter-reviewer:24gb)"
    echo ""
    echo "⚡ Winter Prime Foundation Models:"
    echo "  • winter-prime:8gb-qwen   (alias: winter-prime:8gb, winter-prime:latest) [Qwen2.5-Coder 7B]"
    echo "  • winter-prime:16gb-qwen  (alias: winter-prime:16gb)                     [Qwen2.5-Coder 14B]"
    echo "  • winter-prime:24gb-qwen  (alias: winter-prime:24gb)                     [Qwen2.5-Coder 32B]"
}

TARGET="${1:-list}"

case "${TARGET}" in
    8gb)
        build_8gb
        ;;
    16gb)
        build_16gb
        ;;
    24gb)
        build_24gb
        ;;
    all)
        build_8gb
        build_16gb
        build_24gb
        ;;
    prime-8gb|smmp-8gb)
        build_prime_8gb
        ;;
    prime-16gb|smmp-16gb)
        build_prime_16gb
        ;;
    prime-24gb|smmp-24gb)
        build_prime_24gb
        ;;
    prime|prime-all|smmp|smmp-all)
        build_prime
        ;;
    updated|changed|diff)
        build_updated
        ;;
    *Modelfile*)
        for arg in "$@"; do
            build_by_file "${arg}"
        done
        ;;
    pull-8gb)
        pull_8gb
        ;;
    pull-16gb)
        pull_16gb
        ;;
    pull-24gb)
        pull_24gb
        ;;
    pull-all)
        pull_all
        ;;
    list|--list|-l)
        list_models
        ;;
    *)
        echo "Usage: $0 [8gb | 16gb | 24gb | all | prime-8gb | prime-16gb | prime-24gb | prime | updated | <modelfile>... | pull-8gb | pull-16gb | pull-24gb | pull-all | list]"
        exit 1
        ;;
esac
