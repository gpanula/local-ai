# Task: Hello World Multi-Agent Pipeline Test

## Goal
Write and execute a standalone bash script at `sysadmin/hello_world.sh` that prints "Hello from Ollama Multi-Agent Pipeline" and exits cleanly with code 0.

## Defensive Standards for `sysadmin/hello_world.sh`
1. Enable `set -euo pipefail`.
2. Include an `ERR` diagnostic trap:
   ```bash
   trap 'echo "❌ [ERROR] Script failed on line ${LINENO}" >&2; exit 1' ERR
   ```
3. Emit a success message: `🎉 Hello World test completed successfully`.
4. Ensure the script exits with code 0.

## Implementation Contract
Invoke the `write_file` tool to create `sysadmin/hello_world.sh` with `make_executable: true` containing the robust bash script.

