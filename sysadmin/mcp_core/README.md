# MCP Core Library (`mcp_core`)

A shared core library providing foundational utilities for workspace path confinement, JSON-RPC communication with local Ollama instances, `terminal-mcp` Unix socket bridging, cognitive memory management, trajectory recording, and fine-tuning dataset generation.

Consumed by the command-line interface ([`sysadmin/mcp_cli`](../mcp_cli/README.md)) and the local MCP server backend ([`sysadmin/mcp_ollama/server.py`](../mcp_ollama/server.py)).

---

## 🧩 Core Modules

### 1. Workspace Confinement & Safety (`workspace.py`)
- **[`workspace.py`](workspace.py)**:
  - `WORKSPACE_ROOT`: Dynamically resolved repository root path.
  - `validate_workspace_path(path: str, purpose: str = "file") -> str`: Resolves paths and strictly asserts they reside within `WORKSPACE_ROOT` to prevent path traversal attacks.
  - `is_valid_mcp_socket(path: str) -> bool`: Verifies that a Unix domain socket path exists, is a valid socket, is not a symlink, and is owned by the current user UID.

### 2. Transport & Terminal Session (`transport.py`)
- **[`transport.py`](transport.py)**:
  - `call_mcp(tool_name: str, arguments: dict) -> str`: Executes a JSON-RPC 2.0 `tools/call` invocation against `server.py` over stdio and handles error propagation.
  - `TerminalMCPSession`: Context manager connecting directly to the `/tmp/terminal-mcp.sock` Unix domain socket. Exposes `type` (keystroke injection) and `get_content` (terminal screen buffer retrieval).
  - `send_terminal_mcp(text: str) -> None`: Formats and streams comment-prefixed status updates and banners to both local stdout and the live interactive `terminal-mcp` PTY window.

### 3. Trajectory Recording (`trajectories.py`)
- **[`trajectories.py`](trajectories.py)**:
  - `record_trajectory(pipeline_result, prompt_content, ...)`: Records multi-iteration or single-turn pipeline runs into `sysadmin/data/trajectories.jsonl`.
  - **Structured Multi-Agent Roles**: Captures first-class `roles` sub-objects for `orchestrator`, `coder`, `reviewer`, `security`, `sysadmin`, and `architect` with their respective models and 4-pillar reasoning traces.
  - **Canonical Category Normalization**: Automatically maps each run to a canonical taxonomy domain via `mcp_core.audit.normalize_category()` to eliminate sprawl.
  - **Tiered Storage**: Scripts < 150 lines store inline code; scripts ≥ 150 lines store unified diffs and focused failure snippets inline while offloading verbatim files to `sysadmin/data/raw_trajectories/<id>/`.

### 4. Fine-Tuning Dataset Generation (`dataset.py`)
- **[`dataset.py`](dataset.py)**:
  - `export_datasets(...)`: Exports trajectories into standard formats for local fine-tuning frameworks (Unsloth, TRL, Llama-Factory, Axolotl).
  - **Role Targeting**: Allows exporting role-specific Chain-of-Thought datasets via `--role {coder,orchestrator,reviewer,security,sysadmin,architect}`.
  - **Chain-of-Thought (CoT) SFT Direct**: Formats completions with role-specific 4 pillars (e.g. Coder: `Analysis & Strategy`, `Risks & Edge Cases`, `Implementation`, `Verification & Testing`; Orchestrator: `Analysis`, `Risks`, `Architecture & Plan`, `Acceptance Gates`).
  - **SFT Multi-Turn**: Synthesizes self-correction conversational turns (Prompt ➔ Rejected Script ➔ Reviewer Audit ➔ Corrected Script).
  - **DPO (Direct Preference Optimization)**: Synthesizes `(prompt, chosen, rejected)` triplets annotated with canonical categories.

### 5. Memory & Lesson Extraction (`extraction.py`, `memory.py`, `audit.py`)
- **[`audit.py`](audit.py)**:
  - Dynamic taxonomy loader and category normalizer (`normalize_category`, `load_taxonomy`, `add_taxonomy_domain`) synchronized with `ollama_update/taxonomy.json`.
- **[`extraction.py`](extraction.py)**:
  - `extract_lesson_from_critique`: Mines structured lessons from Reviewer feedback and compiler/linter errors.
  - `extract_lesson_from_stuck_loop`: Detects repeating reviewer signatures in revision loops.
  - `extract_lesson_from_success`: Mines **proactive architectural defenses** (`pre_emptive_defense`) from iteration-1 passes when the model anticipates domain constraints.
- **[`memory.py`](memory.py)**:
  - `MemoryStore`: SQLite-backed cognitive memory (`sysadmin/data/memory.db`) with FTS5 keyword indexing, pending staging queue, and lesson promotion workflows.

### 6. Context Injection & Lesson Formatting (`injection.py`)
- **[`injection.py`](injection.py)**:
  - Extracts significant keyword tokens from task prompts and queries `MemoryStore` to dynamically inject relevant lessons and defensive invariants before the author begins code generation.

### 7. Hardware & Model Tier Management (`hardware.py`)
- **[`hardware.py`](hardware.py)**:
  - Detects hardware tier based on VRAM capacity (8GB, 16GB, 24GB).
  - Resolves default models for `orchestrator`, `coder`, and `reviewer` roles.
  - Manages VRAM residency rules (e.g. keeping 8GB models resident vs. cycling 24GB/32B models).

### 8. Script Sanitization (`sanitize.py`)
- **[`sanitize.py`](sanitize.py)**:
  - `sanitize_script_code(code: str) -> str`: Normalizes extracted shell code, strips indentation, and ensures shell heredoc closing delimiters (`EOF`, `EOT`) align to column 0.

---

## 🚀 Usage & Examples

### Trajectory Logging with Cognitive Reasoning

```python
from mcp_core.trajectories import record_trajectory

record_id = record_trajectory(
    pipeline_result={
        "approved": True,
        "iterations": 1,
        "final_code_block": "#!/bin/bash\nset -euo pipefail\necho 'ok'\n",
        "reasoning": {
            "strategy": "Apply defensive traps and isolate path.",
            "risks": "Non-deterministic behavior if ambient PATH is used.",
            "verification_plan": "Execute with bash -n and verify exit code 0.",
        },
        "author_model": "winter-coder:8gb-trained",
    },
    prompt_content="Write a robust shell script...",
    task_file="sysadmin/prompts/example.md",
)
print(f"Recorded trajectory: {record_id}")
```

### Exporting CoT Fine-Tuning Datasets

```python
from mcp_core.dataset import export_datasets

counts = export_datasets(
    output_dir="sysadmin/data/training",
    formats=["dpo", "sft_direct", "sft_multiturn"],
    approved_only=True,
    include_cot=True,
)
print("Exported dataset counts:", counts)
```
