#!/usr/bin/env bash
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
echo "Hello from Ollama Multi-Agent Pipeline"
echo "🎉 Hello World test completed successfully"
exit 0
