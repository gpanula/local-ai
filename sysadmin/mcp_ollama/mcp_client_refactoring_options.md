# `mcp_client.py` Refactoring Options

## Current State

| File | Lines | Bytes | Responsibilities |
|------|-------|-------|-----------------|
| [`mcp_client.py`](sysadmin/mcp_client.py) | 680 | 36 KB | CLI arg parsing, MCP transport, terminal-mcp I/O, script sanitization, `pipeline-run` orchestration loop, `build-and-run` orchestration, and thin pass-through dispatch for 13 subcommands |
| [`server.py`](sysadmin/mcp_ollama/server.py) | 1,166 | 45 KB | MCP JSON-RPC server, Ollama HTTP client, tool handler implementations, tool schema definitions, terminal-mcp execution, executable resolver |

### Where the pain is

The [`main()`](sysadmin/mcp_client.py#L123-L674) function is a **550-line monolith** containing:

1. **Argument definitions** (L128–L226) — 13 subcommands with ~100 lines of argparse boilerplate
2. **Thin pass-through handlers** (L229–L674) — most subcommands just serialize args → `call_mcp()` → print, but…
3. **Heavyweight embedded orchestration** — [`pipeline-run`](sysadmin/mcp_client.py#L288-L577) alone is **~290 lines** of multi-agent loop logic (authoring, linting, reviewing, stuck-loop detection, execution) inlined directly in the `elif` branch
4. **Duplicated terminal-mcp bootstrap** — the JSON-RPC init handshake for `type`/`view` (L588–L610) is copy-pasted from [`send_terminal_mcp()`](sysadmin/mcp_client.py#L74-L110)
5. **Duplicated utilities** — `_validate_workspace_path` and `_is_valid_mcp_socket` exist in both files with nearly identical implementations

---

## Option A: **Modular Single-Package Decomposition** (Flat `sysadmin/mcp_cli/` package)

Break `mcp_client.py` into a flat Python package where each concern is its own module, preserving the single `python3 -m mcp_cli <subcommand>` entry point.

```
sysadmin/
├── mcp_client.py              → thin shim: `from mcp_cli.__main__ import main; main()`
└── mcp_cli/
    ├── __init__.py             (version, constants)
    ├── __main__.py             (argparse + dispatch table only)
    ├── transport.py            (call_mcp, TerminalMCPSession context manager)
    ├── commands/
    │   ├── __init__.py
    │   ├── ollama.py           (chat, task, task-file, list-models, pull)
    │   ├── pipeline.py         (pipeline-run, build-and-run orchestration)
    │   ├── inspect.py          (shellcheck, ansible-check)
    │   ├── systemd.py          (service-status, journal-logs)
    │   ├── files.py            (write-file, read-file)
    │   └── terminal.py         (type, view)
    └── util.py                 (workspace validation, script sanitization, shared helpers)
```

### Key moves

| What | From | To |
|------|------|----|
| `call_mcp()` + `send_terminal_mcp()` + terminal init handshake | top of `mcp_client.py` | `mcp_cli/transport.py` as a reusable `TerminalMCPSession` context manager |
| Each subcommand's argparse definition + handler | `main()` elif branches | Dedicated `commands/*.py` module with a `register(subparsers)` + `run(args)` pattern |
| `pipeline-run` + `build-and-run` | 290-line elif block | `commands/pipeline.py` with the loop extracted into a testable function |
| `_validate_workspace_path`, `_sanitize_script_code` | scattered | `mcp_cli/util.py`, importable by both client and server |

### Trade-offs

| ✅ Pros | ⚠️ Cons |
|---------|---------|
| Easiest migration path — mechanical refactor, no new dependencies | Doesn't address `server.py` growth |
| Each command is independently testable | Still stdlib-only, so argparse boilerplate stays verbose |
| `mcp_client.py` remains a valid entry point (shim) | Package layout adds a few `__init__.py` files |
| Natural growth path — new subcommands = new file in `commands/` | |

---

## Option B: **Click-Based CLI with Shared Core Library**

Replace argparse with [Click](https://click.palletsprojects.com/) and extract shared code (workspace validation, MCP transport, terminal session management) into a shared `core` library used by both `mcp_client` and `server.py`.

```
sysadmin/
├── mcp_client.py              → `from mcp_cli.cli import cli; cli()`
├── mcp_core/                  ← shared library (used by both client & server)
│   ├── __init__.py
│   ├── workspace.py           (_validate_workspace_path, WORKSPACE_ROOT)
│   ├── transport.py           (call_mcp, TerminalMCPSession)
│   └── sanitize.py            (_sanitize_script_code)
├── mcp_cli/
│   ├── __init__.py
│   ├── cli.py                 (Click group + command auto-discovery)
│   ├── ollama.py              (@cli.command decorators for chat, task, etc.)
│   ├── pipeline.py            (@cli.command for pipeline-run, build-and-run)
│   ├── inspect.py             (@cli.command for shellcheck, ansible-check)
│   ├── systemd.py             (@cli.command for service-status, journal-logs)
│   ├── files.py               (@cli.command for write-file, read-file)
│   └── terminal.py            (@cli.command for type, view)
└── mcp_ollama/
    └── server.py              (imports from mcp_core/ instead of re-implementing)
```

### What Click buys you

```python
# mcp_cli/pipeline.py — Click version
@cli.command("pipeline-run")
@click.argument("file", type=click.Path(exists=True))
@click.option("--author", default="qwen2.5-coder:7b", help="Code author model")
@click.option("--reviewer", default="qwen3:8b", help="Review model")
@click.option("--max-retries", default=2, type=int)
@click.option("--dry-run", is_flag=True)
def pipeline_run(file, author, reviewer, max_retries, dry_run):
    """Multi-agent pipeline: Author → Lint → Review → Execute"""
    ...
```

Each command is self-contained. No giant `main()`. Auto-generated `--help` with rich formatting.

### Trade-offs

| ✅ Pros | ⚠️ Cons |
|---------|---------|
| Click eliminates argparse boilerplate (~100 lines gone) | Adds `click` as a pip dependency in the venv |
| `mcp_core/` eliminates duplication between client & server | Larger refactor surface — server.py also changes imports |
| Rich `--help`, command groups, validation decorators | Learning curve if unfamiliar with Click |
| Plugin-friendly: new `.py` files in `mcp_cli/` auto-register | Ollama-synthesized scripts can't easily `import click` |

---

## Option C: **Command-Object Registry Pattern** (Zero new dependencies)

Keep argparse and zero external dependencies, but refactor into a self-registering command pattern where each subcommand is a class that declares its own args and handler. This is the lightest-touch structural improvement.

```
sysadmin/
├── mcp_client.py              → slim dispatcher (~40 lines)
└── mcp_cli/
    ├── __init__.py
    ├── base.py                (BaseCommand ABC + registry decorator)
    ├── transport.py           (call_mcp, TerminalMCPSession)
    ├── util.py                (workspace validation, sanitization)
    └── commands/
        ├── __init__.py        (imports all command modules to trigger registration)
        ├── ollama.py
        ├── pipeline.py
        ├── inspect.py
        ├── systemd.py
        ├── files.py
        └── terminal.py
```

### The pattern

```python
# mcp_cli/base.py
COMMAND_REGISTRY = {}

class BaseCommand:
    """Each subcommand implements this interface."""
    name: str = ""
    help: str = ""

    def register_args(self, parser: argparse.ArgumentParser):
        """Add arguments to the subparser."""
        ...

    def run(self, args: argparse.Namespace):
        """Execute the command."""
        ...

def command(cls):
    """Class decorator that auto-registers a command."""
    COMMAND_REGISTRY[cls.name] = cls()
    return cls
```

```python
# mcp_cli/commands/pipeline.py
@command
class PipelineRunCommand(BaseCommand):
    name = "pipeline-run"
    help = "Multi-agent pipeline: Author → Lint → Review → Execute"

    def register_args(self, parser):
        parser.add_argument("file", ...)
        parser.add_argument("--author", default="qwen2.5-coder:7b")
        ...

    def run(self, args):
        # The 290 lines of pipeline logic live here, cleanly isolated
        ...
```

```python
# mcp_client.py — now ~40 lines
from mcp_cli.base import COMMAND_REGISTRY
import mcp_cli.commands  # triggers registration

def main():
    parser = argparse.ArgumentParser(description="Ollama MCP Client CLI")
    subs = parser.add_subparsers(dest="command", required=True)
    for name, cmd in COMMAND_REGISTRY.items():
        sub = subs.add_parser(name, help=cmd.help)
        cmd.register_args(sub)
    args = parser.parse_args()
    COMMAND_REGISTRY[args.command].run(args)
```

### Trade-offs

| ✅ Pros | ⚠️ Cons |
|---------|---------|
| Zero new dependencies — pure stdlib | More boilerplate per command than Click |
| `mcp_client.py` becomes a 40-line dispatcher | Doesn't address `server.py` duplication (could add `mcp_core/` optionally) |
| Each command is independently testable and isolated | Class-based pattern can feel heavyweight for simple pass-throughs |
| Self-registering: new file in `commands/` = new subcommand, nothing else to touch | No auto-generated rich help formatting |
| Familiar OOP pattern, easy for Ollama-generated code to follow | |

---

## Comparison Matrix

| Criterion | **A: Flat Package** | **B: Click + Core** | **C: Command Registry** |
|-----------|:---:|:---:|:---:|
| New dependencies | None | `click` | None |
| Migration effort | Low | Medium | Low-Medium |
| Fixes client/server duplication | ❌ | ✅ | ❌ (optional) |
| Eliminates argparse boilerplate | ❌ | ✅ | ❌ |
| Testability of `pipeline-run` | ✅ | ✅ | ✅ |
| Growth path (new commands) | Good | Excellent | Excellent |
| Ollama-compatible (no exotic imports) | ✅ | ⚠️ | ✅ |
| `mcp_client.py` stays as entry point | ✅ shim | ✅ shim | ✅ shim |

> [!TIP]
> My recommendation: **Option C** gives you the best ratio of structural improvement to disruption. It solves the primary pain (the 550-line `main()` monolith) with zero new dependencies, and leaves the door open to adopt `mcp_core/` from Option B later if `server.py` duplication becomes a friction point.
>
> Option A is also completely viable and simpler — it's essentially Option C without the registry pattern, relying on a manual dispatch dict instead.
