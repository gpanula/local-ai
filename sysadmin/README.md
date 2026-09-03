# Linux SysAdmin & Autonomous Local AI Engineering

This directory houses the autonomous multi-agent toolchain, cognitive memory systems, and fine-tuning pipelines that enable self-hosted Ollama models to perform Linux systems administration, defensive automation, and iterative self-correction.

---

## 🏗️ System Architecture & Workflow

The architecture unites local models, sandboxed interactive terminals, a persistent cognitive learning loop, and a **Dual-Axis Taxonomy System**:

```
┌────────────────────────────────────────────────────────────────────────┐
│             Vertical Domain Taxonomy (taxonomy.json)                   │
│   • Defensive Bash Scripting       • Binary Isolation                  │
│   • ShellCheck                     • Ansible & Automation              │
│   • Python Quality                 • Code Quality Toolchain            │
│   • Docker & Containerization      • Security & Hardening              │
│   • Multi-Agent Orchestration      • System Architecture               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │  Enforces canonical categories &
                                    │  prevents lesson sprawl
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Horizontal Cognitive Taxonomy (The 6 Roles)                │
│   1. Architect    2. Coder       3. Orchestrator                        │
│   4. Reviewer     5. Security    6. Sysadmin                           │
│                                                                        │
│   Standard 4-Pillar Contract across every role:                        │
│   [Pillar 1: Analysis]   [Pillar 2: Risks]                             │
│   [Pillar 3: Solution]   [Pillar 4: Verification]                      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│     Orchestrator ➔ Author (Coder) ➔ Linter (ShellCheck) ➔ Reviewer     │
│   • Injected Lessons from MemoryStore (FTS5 contextual retrieval)      │
│   • Universal System Rules (Defensive bash standards)                  │
│   • Live PTY Streaming of all cognitive traces to terminal-mcp         │
└───────────────────┬───────────────────────────────┬────────────────────┘
                    │                               │
            Approved (Pass)                   Critique Loop
                    │                               │
                    ▼                               ▼
    ┌───────────────────────────────┐ ┌──────────────────────────────────┐
    │  Live Execution (terminal-mcp)│ │     Iterative Rework Loop        │
    │  • Unix socket / fallback     │ │     • Max revision retries       │
    │  • Verification by Reviewer   │ │     • Re-linting on each attempt │
    └───────────────┬───────────────┘ └──────────────┬───────────────────┘
                    │                                │
                    ▼                                ▼
    ┌────────────────────────────────────────────────────────────────────┐
    │                     Continuous Learning Loop                       │
    │  1. Positive Pattern Mining: Pre-emptive risk mitigations          │
    │  2. Negative Pattern Mining: Reviewer critiques & stuck loops      │
    │  3. Trajectory Logging: Structured multi-agent `roles` dict       │
    │  4. Dataset Exporter: Role-targeted CoT SFT & DPO datasets        │
    └────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Directory Structure

* **[`mcp_cli/`](mcp_cli/README.md)**: Extensible command-registry CLI providing subcommands for pipeline execution (`pipeline-run`, `build-and-run`), dataset exporting (`export-dataset`), memory lifecycle (`memory-*`), static analysis (`shellcheck`, `ansible-check`), and VRAM verification. Invocable via [`mcp_client.py`](mcp_client.py).
* **[`mcp_core/`](mcp_core/README.md)**: Shared core library providing:
  * Workspace path confinement & socket security (`workspace.py`)
  * Unix socket PTY session bridge & stdio MCP transport (`transport.py`)
  * Trajectory recording with tiered offloading & reasoning capture (`trajectories.py`)
  * Chain-of-Thought dataset export for SFT and DPO (`dataset.py`)
  * Dual-mode lesson extraction for failures and proactive defenses (`extraction.py`)
  * SQLite persistent cognitive memory with FTS5 keyword indexing (`memory.py`)
  * In-context lesson injection (`injection.py`)
  * Hardware tier detection (8GB / 16GB / 24GB) and residency rules (`hardware.py`)
* **[`mcp_ollama/`](mcp_ollama/README.md)**: Zero-dependency stdio Model Context Protocol server ([`server.py`](mcp_ollama/server.py)) exposing 12 tools for local model inference, PTY execution, syntax checking, and systemd inspection.
* **[`prompts/`](prompts/)**: Reusable task prompts and test specifications.
* **[`data/`](data/)**: Persistent stores for cognitive memory (`memory.db`), trajectories (`trajectories.jsonl`), raw diffs, and generated training sets (`training/`).

---

## ⚡ Execution Modes (per `AGENTS.md`)

1. ⚡ **Direct Dev Mode** *(Default for infrastructure, tooling, memory, modelfiles, datasets)*:
   - Antigravity directly authors, patches, and tests code (`sysadmin/*.py`, `sysadmin/*.sh`, modelfiles, unit tests) for rapid iteration.
2. 🤖 **Pipeline Delegation Mode** *(Activated explicitly: `"run pipeline"`, `"delegate"`, `"test local ai"`)*:
   - Antigravity writes the prompt spec (`sysadmin/prompts/*.md`); awaits user approval; then delegates execution to the local Ollama multi-agent pipeline.

---

## 🧪 Testing & Verification

Run the entire unit and integration test suite using the isolated virtual environment:

```bash
sysadmin/venv/bin/pytest sysadmin/tests/
```
