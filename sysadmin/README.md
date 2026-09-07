# Linux SysAdmin & Autonomous Local AI Engineering

This directory houses the autonomous multi-agent toolchain, cognitive memory systems, and fine-tuning pipelines that enable self-hosted Ollama models to perform Linux systems administration, defensive automation, and iterative self-correction.

---

## 🏗️ System Architecture & Workflow

The architecture unites local models, sandboxed interactive terminals, a persistent cognitive learning loop, and a **Dual-Axis Taxonomy System**:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Vertical Domain Taxonomy (taxonomy.json)                        │
│   • Defensive Bash Scripting       • Binary Isolation                                  │
│   • ShellCheck                     • Ansible & Automation                              │
│   • Python Quality                 • Code Quality Toolchain                            │
│   • Docker & Containerization      • Security & Hardening                              │
│   • Multi-Agent Orchestration      • System Architecture                               │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │  Enforces canonical categories &
                                            │  prevents lesson sprawl
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Horizontal Cognitive Taxonomy (The 6 Roles)                     │
│   1. Architect    2. Orchestrator    3. Reviewer    4. Security    5. Coder    6. Sysadmin │
│                                                                                        │
│   Standard 4-Pillar Contract across every role:                                        │
│   [Pillar 1: Analysis & Strategy]         [Pillar 2: Risks & Edge Cases]               │
│   [Pillar 3: Solution & Decisions]        [Pillar 4: Verification & Testing]           │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                       Arc-Orc-Rev Planning & Governance Phase                          │
│   1. Architect Phase: Task decomposition + System Architecture memory injection        │
│   2. Orchestrator Phase: DAG construction + Multi-Agent Orchestration memory injection │
│   3. Reviewer Phase: Deterministic pre-filter + LLM audit with dynamic heuristics      │
│   4. Security Phase: STRIDE threat modeling & sandbox constraint verification          │
│      └─ Rejection Loop: Returns to Architect (scope) or Orchestrator (assignment)      │
│      └─ Clearance: Solved pattern captured if remediated; utility credited if clean    │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ (Cleared)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                       Dispatch & Pre-Execution Verification Phase                      │
│   5. Coder Phase: Synthesizes script artifacts via write_file                         │
│   6. Multi-Tier Pre-Execution Code Gates (Zero Uninspected Execution):                │
│      ├─ Tier 1 (Deterministic Linter Gate): ShellCheck, Python AST, path containment   │
│      ├─ Tier 2A (Reviewer Code Gate): Error traps, assertion checks, venv isolation    │
│      └─ Tier 2B (Security Behavioral Gate): Privilege escalation, network, sandboxing  │
│      └─ Rejection: Bounded rework loop returning critique to Coder                     │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ (Approved by all 3 tiers)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                       Live Terminal Execution & Continuous Learning                    │
│   7. Sysadmin Phase: Executes verified scripts live in terminal-mcp (PTY session)     │
│   8. Continuous Learning & Trajectory Engine:                                          │
│      ├─ Trajectory Persistence: Appends multi-agent run to trajectories.jsonl          │
│      ├─ Proactive Mining: Mines pre-emptive mitigations into proven_pattern lessons    │
│      ├─ Telemetry Updates: Increments retrieval counts and prevented rework metrics    │
│      └─ SFT / DPO Exporter: Exports role-targeted CoT datasets for local fine-tuning   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Directory Structure

* **[`pipeline.py`](pipeline.py)**: The Arc-Orc-Rev multi-agent pipeline runner (RFC v7). Implements the state machine (`architect` ➔ `orchestrator` ➔ `reviewer` ➔ `security` ➔ `dispatch`), anti-loop plan hashing, pre-execution code review gates, multi-stage memory injection, and trajectory recording.
* **[`validator.py`](validator.py)**: Deterministic verification engine enforcing:
  - Plan structure, DAG validity, and role assignment (`validate_annotated_plan`).
  - Pre-execution code linting: ShellCheck (`SC2086`, `SC2164`, `SC2181`), Python AST syntax, `/home/` sanitization, and path containment (`validate_code_output`).
* **[`prompts/roles/`](prompts/roles/)**: Canonical role system prompts:
  - Planning: [`architect.md`](prompts/roles/architect.md), [`orchestrator.md`](prompts/roles/orchestrator.md), [`reviewer.md`](prompts/roles/reviewer.md), [`security.md`](prompts/roles/security.md).
  - Pre-Execution Gates: [`reviewer_code.md`](prompts/roles/reviewer_code.md), [`security_code.md`](prompts/roles/security_code.md).
  - Execution: [`coder.md`](prompts/roles/coder.md), [`sysadmin.md`](prompts/roles/sysadmin.md).
* **[`mcp_cli/`](mcp_cli/README.md)**: Extensible command-registry CLI providing subcommands for pipeline execution (`pipeline-run`, `build-and-run`), dataset exporting (`export-dataset`), memory lifecycle (`memory-*`), static analysis (`shellcheck`, `ansible-check`), and VRAM verification. Invocable via [`mcp_client.py`](mcp_client.py).
* **[`mcp_core/`](mcp_core/README.md)**: Shared core library providing:
  - Workspace path confinement & socket security (`workspace.py`)
  - Unix socket PTY session bridge & stdio MCP transport (`transport.py`)
  - Trajectory recording with tiered offloading & reasoning capture (`trajectories.py`)
  - Chain-of-Thought dataset export for SFT and DPO (`dataset.py`)
  - Dual-mode lesson extraction for failures and proactive defenses (`extraction.py`)
  - SQLite persistent cognitive memory with FTS5 keyword indexing (`memory.py`)
  - In-context lesson injection (`injection.py`)
  - Hardware tier detection (8GB / 16GB / 24GB) and residency rules (`hardware.py`)
  - Script sanitization and heredoc alignment (`sanitize.py`)
* **[`mcp_ollama/`](mcp_ollama/README.md)**: Zero-dependency stdio Model Context Protocol server ([`server.py`](mcp_ollama/server.py)) exposing 12 tools for local model inference, PTY execution, syntax checking, and systemd inspection.
* **[`prompts/`](prompts/)**: Reusable task prompts, integration test specifications, and benchmarks.
* **[`data/`](data/)**: Persistent stores for cognitive memory (`memory.db`), trajectories (`trajectories.jsonl`), run state (`runs/<run_id>/`), raw diffs, and generated training sets (`training/`).

---

## 🛠️ Toolchain & Setup Scripts

* **[`setup_graphify.sh`](setup_graphify.sh)**: Deterministic installer for [Graphify](https://github.com/Graphify-Labs/graphify) (`graphifyy`) into `sysadmin/venv` using standard `pip` (without `uv`).
* **[`setup_p0_toolchain.sh`](setup_p0_toolchain.sh)**: P0 toolchain setup (Ansible, ansible-lint, ShellCheck, PyYAML, pytest, sqlite-vec).
* **[`shell_aliases.sh`](shell_aliases.sh)**: Shell aliases including `localai-graphify`, terminal MCP launchers, and Ollama model controls.
* **[`start_terminal_mcp.sh`](start_terminal_mcp.sh)**: Script to start sandboxed `terminal-mcp` with asciinema session recording.

---

## 🚀 Pipeline Execution

### 1. Launching the Multi-Agent Pipeline
Execute any prompt markdown or string through the full Arc-Orc-Rev state machine:

```bash
# Execute from task prompt file
sysadmin/venv/bin/python sysadmin/pipeline.py sysadmin/prompts/hello_world_test.md

# Execute with explicit model override
sysadmin/venv/bin/python sysadmin/pipeline.py sysadmin/prompts/hello_world_test.md --model winter-prime:latest
```

### 2. Resuming Checkpointed or Aborted Runs
If a run paused for human escalation or was interrupted, resume directly from its stored `state.json`:

```bash
sysadmin/venv/bin/python sysadmin/pipeline.py --resume <RUN_ID>
```

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
