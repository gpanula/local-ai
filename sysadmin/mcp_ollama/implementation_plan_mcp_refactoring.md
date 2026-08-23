# Refactor `mcp_client.py` — Option D: Argparse Registry + Shared Core Library

Decompose the 680-line monolithic [`mcp_client.py`](sysadmin/mcp_client.py) into a command-registry CLI package (`mcp_cli/`) and a shared core library (`mcp_core/`) that eliminates duplication with [`server.py`](sysadmin/mcp_ollama/server.py). Zero new dependencies. Click-ready for a future swap.

## User Review Required

> [!IMPORTANT]
> **Entry point compatibility**: `mcp_client.py` will become a thin shim (`from mcp_cli.cli import main; main()`). All existing invocations (`python3 sysadmin/mcp_client.py <subcommand>`) and shell aliases continue to work unchanged.

> [!IMPORTANT]
> **`server.py` import changes**: `server.py` will be updated to `from mcp_core.workspace import ...` instead of defining its own `_validate_workspace_path` / `_is_valid_mcp_socket`. This is a safe mechanical refactor (identical implementations), but it does touch the server.

## Resolved Questions

1. **`python -m mcp_cli` entry point**: ✅ Yes — add [`mcp_cli/__main__.py`](#new-mcp_cli__main__py) and exercise `python3 -m mcp_cli <subcommand>` in the smoke-test loop. Requires `sysadmin/` on `sys.path` (run from `sysadmin/` or use `PYTHONPATH=sysadmin`).
2. **Test scaffolding**: ✅ Yes — add `sysadmin/tests/` with pytest fixtures that mock `call_mcp` and `TerminalMCPSession`; live integration tests are optional and `pytest.skip()` when Ollama/terminal-mcp are unavailable.
3. **Branch name**: No preference — proceed with `feat/mcp-cli-refactor` (matches the [`CONTRIBUTING.md`](../../CONTRIBUTING.md) branch standard).

## Proposed Changes

### Target Directory Structure

```
sysadmin/
├── mcp_client.py                  [MODIFY] → thin shim (5 lines)
├── mcp_core/                      [NEW] shared library
│   ├── __init__.py
│   ├── workspace.py               (validate_workspace_path, WORKSPACE_ROOT, is_valid_mcp_socket)
│   ├── transport.py               (call_mcp, TerminalMCPSession context manager)
│   └── sanitize.py                (sanitize_script_code)
├── mcp_cli/                       [NEW] CLI package
│   ├── __init__.py
│   ├── __main__.py                (enables `python3 -m mcp_cli`)
│   ├── cli.py                     (argparse dispatcher + registry wiring, ~40 lines)
│   ├── base.py                    (BaseCommand ABC + @command registry decorator)
│   └── commands/
│       ├── __init__.py            (imports all modules to trigger registration)
│       ├── ollama.py              (chat, task, task-file, list-models, pull, exec)
│       ├── pipeline.py            (pipeline-run, build-and-run)
│       ├── inspect.py             (shellcheck, ansible-check)
│       ├── systemd.py             (service-status, journal-logs)
│       ├── files.py               (write-file, read-file)
│       └── terminal.py            (type, view)
├── tests/                         [NEW] pytest suite (mocked — no live Ollama/terminal-mcp)
│   ├── conftest.py                (fixtures: fake_call_mcp, fake_terminal_session)
│   ├── test_workspace.py          (validate_workspace_path, is_valid_mcp_socket)
│   ├── test_sanitize.py           (sanitize_script_code)
│   ├── test_cli.py                (registry wiring + per-subcommand --help smoke)
│   └── test_pipeline.py           (revision-loop logic, mocked)
└── mcp_ollama/
    └── server.py                  [MODIFY] imports from mcp_core/ instead of local definitions
```

---

### Shared Core Library — `mcp_core/`

Extracts the utilities duplicated between `mcp_client.py` and `server.py` into a single source of truth.

#### [NEW] `mcp_core/__init__.py`

Empty init, package marker.

#### [NEW] `mcp_core/workspace.py`

Moves from both files (renamed to public API — no leading underscore):
- `WORKSPACE_ROOT` constant (computed relative to `mcp_core/`'s location: `../../`)
- [`validate_workspace_path()`](sysadmin/mcp_ollama/server.py#L44-L56) — canonicalized to **server.py semantics**: empty/whitespace guard + relative paths resolve against `WORKSPACE_ROOT` (stricter, safer)
- [`is_valid_mcp_socket()`](sysadmin/mcp_client.py#L27-L37) — identical in both files

> [!NOTE]
> This is a deliberate behavior change on the CLI side: `mcp_client.py`'s current `_validate_workspace_path()` resolves relative paths against the current working directory. After consolidation, CLI commands that accept paths (`task-file`, `build-and-run`, `pipeline-run`, `ansible-check`, `shellcheck`) resolve relative paths against `WORKSPACE_ROOT` instead. Verify with a relative-path invocation during smoke testing.

#### [NEW] `mcp_core/transport.py`

Extracts from `mcp_client.py`:
- [`call_mcp()`](sysadmin/mcp_client.py#L40-L71) — JSON-RPC subprocess transport to `server.py`
- [`send_terminal_mcp()`](sysadmin/mcp_client.py#L74-L110) — terminal-mcp PTY streaming
- **New**: `TerminalMCPSession` context manager that encapsulates the JSON-RPC init handshake (currently copy-pasted in `send_terminal_mcp`, `type` command, and `view` command)

```python
class TerminalMCPSession:
    """Context manager for terminal-mcp JSON-RPC sessions.
    
    Eliminates the 3x copy-pasted init handshake pattern.
    """
    def __enter__(self):
        self._proc = subprocess.Popen(...)
        # init + notifications/initialized handshake
        return self

    def type(self, text: str): ...
    def get_content(self, visible_only: bool = False) -> str: ...

    def __exit__(self, *exc):
        self._proc.terminate()
```

#### [NEW] `mcp_core/sanitize.py`

Moves [`_sanitize_script_code()`](sysadmin/mcp_client.py#L113-L120) here as public `sanitize_script_code()`.

---

### CLI Package — `mcp_cli/`

#### [NEW] `mcp_cli/base.py`

The command registry pattern:

```python
import argparse
from abc import ABC, abstractmethod

COMMAND_REGISTRY: dict[str, "BaseCommand"] = {}

class BaseCommand(ABC):
    """Base class for all CLI subcommands."""
    name: str = ""
    help: str = ""

    @abstractmethod
    def register_args(self, parser: argparse.ArgumentParser) -> None:
        """Add command-specific arguments to the subparser."""

    @abstractmethod
    def run(self, args: argparse.Namespace) -> None:
        """Execute the command."""

def command(cls):
    """Class decorator — auto-registers a BaseCommand subclass."""
    instance = cls()
    COMMAND_REGISTRY[instance.name] = instance
    return cls
```

> [!TIP]
> **Click migration path**: When/if you adopt Click, you replace `BaseCommand.register_args()` with `@click.option` decorators and swap the dispatcher in `cli.py`. The `commands/` module files stay in the same place, only the method signatures change.

#### [NEW] `mcp_cli/cli.py`

The slim dispatcher (~40 lines):

```python
import argparse
import logging
from mcp_cli.base import COMMAND_REGISTRY
import mcp_cli.commands  # noqa: F401 — triggers registration

def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ollama MCP Client CLI")
    subs = parser.add_subparsers(dest="command", required=True)

    for name, cmd in COMMAND_REGISTRY.items():
        sub = subs.add_parser(name, help=cmd.help)
        cmd.register_args(sub)

    args = parser.parse_args()
    COMMAND_REGISTRY[args.command].run(args)
```

#### [NEW] `mcp_cli/__main__.py`

```python
from mcp_cli.cli import main
main()
```

#### [NEW] `mcp_cli/commands/__init__.py`

Imports all command modules to trigger `@command` registration:

```python
from mcp_cli.commands import ollama, pipeline, inspect, systemd, files, terminal  # noqa: F401
```

#### [NEW] `mcp_cli/commands/ollama.py`

Contains 5 commands currently in `main()`:
- `list-models` (L229–L231)
- `pull` (L232–L235)
- `chat` (L236–L242)
- `task` (L243–L250)
- `task-file` (L251–L260)
- `exec` (L578–L585)

Each is a `@command` class, e.g.:

```python
@command
class ChatCommand(BaseCommand):
    name = "chat"
    help = "Send chat prompt"

    def register_args(self, parser):
        parser.add_argument("prompt", help="Prompt text")
        parser.add_argument("--model", default="qwen3:8b")
        parser.add_argument("--system", default=None)

    def run(self, args):
        out = call_mcp("ollama_chat", {
            "prompt": args.prompt,
            "model": args.model,
            "system_prompt": args.system,
        })
        print(out)
```

#### [NEW] `mcp_cli/commands/pipeline.py`

The big one. Contains:
- [`build-and-run`](sysadmin/mcp_client.py#L261-L287) (~25 lines)
- [`pipeline-run`](sysadmin/mcp_client.py#L288-L577) (~290 lines)

The pipeline loop logic moves into a dedicated method, making it independently testable:

```python
@command
class PipelineRunCommand(BaseCommand):
    name = "pipeline-run"
    help = "Multi-agent pipeline: Author → Lint → Review → Execute"

    def register_args(self, parser):
        parser.add_argument("file", ...)
        parser.add_argument("--author", default="qwen2.5-coder:7b")
        # ... all existing args ...

    def run(self, args):
        prompt_content = self._load_prompt(args.file)
        code, approved = self._revision_loop(prompt_content, args)
        if approved and not args.dry_run:
            self._execute(code, args)

    def _revision_loop(self, prompt_content, args):
        """Author → Lint → Review cycle. Returns (final_code, approved)."""
        ...

    def _execute(self, code, args):
        """Step 4: Live terminal execution of approved code."""
        ...
```

#### [NEW] `mcp_cli/commands/inspect.py`

- `shellcheck` (L624–L635)
- `ansible-check` (L611–L623)

#### [NEW] `mcp_cli/commands/systemd.py`

- `service-status` (L636–L641)
- `journal-logs` (L642–L649)

#### [NEW] `mcp_cli/commands/files.py`

- `write-file` (L650–L666)
- `read-file` (L667–L674)

#### [NEW] `mcp_cli/commands/terminal.py`

- `type` (L586–L598) — refactored to use `TerminalMCPSession`
- `view` (L599–L610) — refactored to use `TerminalMCPSession`

---

### Server Modifications

#### [MODIFY] [`mcp_ollama/server.py`](sysadmin/mcp_ollama/server.py)

Replace the duplicated local definitions with imports from `mcp_core`:

```diff
-WORKSPACE_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
-
-def _validate_workspace_path(path: str, purpose: str = "file") -> str:
-    ...
-
-def _is_valid_mcp_socket(path: str) -> bool:
-    ...
+import sys
+sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))
+from mcp_core.workspace import WORKSPACE_ROOT, validate_workspace_path, is_valid_mcp_socket
```

> [!NOTE]
> The `sys.path` manipulation is needed because `server.py` is invoked as a standalone script by `call_mcp()` (via `subprocess.run`), not as a module import. The path insert ensures `mcp_core` is discoverable. An alternative is setting `PYTHONPATH` in `call_mcp()`.

---

### Entry Point Shim

#### [MODIFY] [`mcp_client.py`](sysadmin/mcp_client.py)

```python
#!/usr/bin/env python3
"""Lightweight CLI Client for Local Ollama MCP Server."""
from mcp_cli.cli import main

if __name__ == "__main__":
    main()
```

All existing invocations (`python3 sysadmin/mcp_client.py pipeline-run ...`) continue to work.

---

## Migration Strategy

The refactor is **purely structural** — no behavioral changes. Proposed order:

1. **Create `mcp_core/`** — extract shared utilities, update `server.py` imports, verify server still works via `mcp_client.py list-models`
2. **Create `mcp_cli/base.py` + `cli.py`** — registry infrastructure
3. **Migrate simple commands first** — `ollama.py`, `files.py`, `systemd.py`, `terminal.py`, `inspect.py` (these are all thin pass-throughs, ~5–15 lines each)
4. **Migrate `pipeline.py`** — the complex one, extract revision loop into testable methods
5. **Replace `mcp_client.py`** with shim
6. **Smoke test** every subcommand

## Verification Plan

### Unit Tests (pytest, mocked)

`sysadmin/tests/` uses `pytest` with two shared fixtures in `conftest.py`:

- `fake_call_mcp` — monkeypatches `mcp_core.transport.call_mcp` to return canned JSON-RPC results (no subprocess, no live server)
- `fake_terminal_session` — monkeypatches `TerminalMCPSession` with an in-memory fake (no `npx`, no live PTY)

Live integration tests (real Ollama + terminal-mcp) live in `sysadmin/tests/integration/` and `pytest.skip()` when `OLLAMA_HOST` is unreachable or no terminal-mcp socket is present.

```bash
python3 -m pytest sysadmin/tests/ -q
```

### Automated Tests

```bash
# Quick smoke: does every subcommand parse --help without errors (both entry points)?
for cmd in list-models pull chat task task-file exec build-and-run pipeline-run \
           type view ansible-check shellcheck service-status journal-logs \
           write-file read-file; do
    python3 sysadmin/mcp_client.py "$cmd" --help
    PYTHONPATH=sysadmin python3 -m mcp_cli "$cmd" --help
done

# Functional: list-models round-trip through server
python3 sysadmin/mcp_client.py list-models

# Verify server.py still processes JSON-RPC correctly
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 sysadmin/mcp_ollama/server.py
```

### Manual Verification

- Run `pipeline-run` with `--dry-run` against an existing prompt file to verify the full orchestration loop still works end-to-end
- Confirm shell aliases in [`shell_aliases.sh`](sysadmin/shell_aliases.sh) still resolve correctly
- Confirm `python3 -m mcp_cli` works as an alternative entry point (e.g. `PYTHONPATH=sysadmin python3 -m mcp_cli list-models`)
- Verify a **relative** path argument to `task-file` / `shellcheck` now resolves against `WORKSPACE_ROOT` (canonicalized server semantics) rather than the CWD
