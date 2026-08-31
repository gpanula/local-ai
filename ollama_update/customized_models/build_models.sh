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
    build_model "24gb" "Modelfile-sysadmin-codestral"     "winter-sysadmin:24gb-codestral"  "winter-sysadmin:24gb"
    build_model "24gb" "Modelfile-security-codestral"     "winter-security:24gb-codestral"  "winter-security:24gb"
    build_model "24gb" "Modelfile-reviewer-codestral"     "winter-reviewer:24gb-codestral"  "winter-reviewer:24gb"
    echo "🎉 All 24GB tier models built successfully!"
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
    echo "  • winter-sysadmin:24gb-codestral  (alias: winter-sysadmin:24gb)"
    echo "  • winter-security:24gb-codestral  (alias: winter-security:24gb)"
    echo "  • winter-reviewer:24gb-codestral  (alias: winter-reviewer:24gb)"
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
        echo "Usage: $0 [8gb | 16gb | 24gb | all | pull-8gb | pull-16gb | pull-24gb | pull-all | list]"
        exit 1
        ;;
esac
