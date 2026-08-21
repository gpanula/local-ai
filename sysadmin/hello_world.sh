#!/bin/bash
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR

# Main script content
printf "Hello from Ollama Multi-Agent Pipeline\n"

# Success message
echo "🎉 Hello World test completed successfully"
exit 0