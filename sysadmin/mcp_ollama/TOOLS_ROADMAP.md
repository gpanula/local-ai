# Ollama Tooling & Capability Roadmap

This document catalogs the planned tools to expose to the local Ollama agent (`qwen2.5-coder:7b`, `qwen3:8b`, `mistral-nemo:12b`) via our Model Context Protocol (MCP) server (`sysadmin/mcp_ollama/server.py`) and agent harnesses (Loom, Fincept, SysAdmin).

---

## 🎯 Architecture & Guiding Principles

1. **Role Division ([Rule 8 `AGENTS.md`](../../AGENTS.md))**:
   * **Antigravity IDE (Orchestrator)**: Authors high-level prompts and task specifications (`sysadmin/prompts/*.md`).
   * **Local Ollama Agent (Executor)**: Autonomously invokes tools, synthesizes scripts, and runs live self-verification.
2. **Safety & Verification First ([Rule 4 `AGENTS.md`](../../AGENTS.md))**:
   * Inspection tools must default to **read-only** or **dry-run/check-mode**.
   * Code generation must pass pre-flight linters before execution.
3. **Context Efficiency**:
   * Tools must return compact, bounded summaries rather than raw unbounded buffers to avoid saturating 4k/8k context windows.

---

## 🛠️ Tool Catalog by Functional Domain

### 1. Code Quality & Pre-Flight Linters
*Purpose: Provide Ollama with fast, in-memory validation of generated code before writing to disk or executing.*

* **`python_syntax_check`**:
  * **Function**: In-memory compilation (`py_compile` / `ast.parse`) to verify syntax, imports, and syntax tree validity.
  * **Target Model**: `qwen2.5-coder:7b`
  * **Primary Domain**: `/sysadmin` (Python Ansible modules, custom scripts)
* **`ansible_syntax_check` & `ansible_lint`**:
  * **Function**: Executes `ansible-playbook --syntax-check` and `ansible-lint` against generated YAML and task lists.
  * **Target Model**: `qwen2.5-coder:7b`
  * **Primary Domain**: `/sysadmin` (Ansible playbooks, roles, tasks)
* **`shellcheck_inspect`**:
  * **Function**: Runs `shellcheck -s bash` on synthesized bash scripts to catch unquoted variables, unhandled error traps, and syntax errors.
  * **Target Model**: `qwen2.5-coder:7b`
  * **Primary Domain**: `/sysadmin` (Shell scripts, heredocs)

---

### 2. Linux SysAdmin & Diagnostic Inspection (Read-Only)
*Purpose: Enable Ollama to diagnose system state, troubleshoot failures, and verify service behavior without unrestricted root access.*

* **`service_status`**:
  * **Function**: Query `systemctl status <unit>` or list failed units (`systemctl --failed --no-pager`).
  * **Target Model**: `qwen3:8b`
  * **Primary Domain**: `/sysadmin` (System triage)
* **`journal_logs`**:
  * **Function**: Fetch bounded logs for specific systemd units or priorities (`journalctl -u <unit> -n <lines> --no-pager`).
  * **Target Model**: `qwen3:8b`
  * **Primary Domain**: `/sysadmin` (Log analysis)
* **`port_process_inspect`**:
  * **Function**: Query listening sockets, ports, and associated PIDs (`ss -tulpn` or `lsof -i :<port>`).
  * **Target Model**: `qwen3:8b`
  * **Primary Domain**: `/sysadmin` (Network diagnostics)
* **`network_route_inspect`**:
  * **Function**: Inspect IP routes, link status, and firewall rules (`ip route`, `ip link`, `nft list ruleset`).
  * **Target Model**: `qwen3:8b`
  * **Primary Domain**: `/sysadmin` (Network verification)

---

### 3. File & Diff Sandbox Tools
*Purpose: Provide safe, chunked filesystem interaction and self-review capabilities.*

* **`file_read_chunk`**:
  * **Function**: Read specific line ranges or grep patterns from files to prevent context window saturation.
  * **Target Model**: `qwen2.5-coder:7b` / `qwen3:8b`
  * **Primary Domain**: All pillars
* **`git_diff_inspect`**:
  * **Function**: Run `git diff --stat` or `git diff <file>` to let Ollama self-review generated diffs before marking tasks complete.
  * **Target Model**: `qwen2.5-coder:7b`
  * **Primary Domain**: All pillars
* **`snapshot_undo`**:
  * **Function**: Create temporary workspace checkpoints before running destructive actions and roll back on failure.
  * **Target Model**: `qwen3:8b`
  * **Primary Domain**: `/loom` & `/sysadmin`

---

### 4. GPU & Hardware Telemetry
*Purpose: Enable empirical benchmarking and dynamic layer offloading for MoE research on the Quadro P4200 (8 GB VRAM).*

* **`gpu_telemetry`**:
  * **Function**: Query exact VRAM residency, PCIe bandwidth, compute utilization, and temperature (`nvidia-smi --query-gpu=...`).
  * **Target Model**: Both models
  * **Primary Domain**: `/moe` (VRAM budgeting for `olmoe:7b`, `mixtral:8x7b`)
* **`benchmark_inference_speed`**:
  * **Function**: Run automated token-per-second and time-to-first-token benchmarks across context lengths (1k, 2k, 4k, 8k).
  * **Target Model**: Both models
  * **Primary Domain**: `/moe`

---

### 5. Loom & SQLite State Management
*Purpose: Facilitate lossless multi-agent memory and role delegation.*

* **`sqlite_query`**:
  * **Function**: Read and query Loom’s conversation recall and task state database (`conversation_recall.db`).
  * **Target Model**: `qwen3:8b`
  * **Primary Domain**: `/loom` & `/fincept`
* **`subtask_delegate`**:
  * **Function**: Allow a planner model (`qwen3:8b`) to dispatch targeted subtasks directly to the coding engine (`qwen2.5-coder:7b`).
  * **Target Model**: `qwen3:8b`
  * **Primary Domain**: `/loom`

---

## 📅 Rollout Priority & Phase Plan

| Priority | Tool Name | Target Model | Primary Pillar | Description |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | `ansible_syntax_check` | `qwen2.5-coder:7b` | `/sysadmin` | Syntax and argument validation for Ansible modules/playbooks |
| **P0** | `shellcheck_inspect` | `qwen2.5-coder:7b` | `/sysadmin` | Static analysis for synthesized bash scripts |
| **P0** | `service_status` & `journal_logs` | `qwen3:8b` | `/sysadmin` | Bounded inspection of system services and journal streams |
| **P1** | `gpu_telemetry` | Both | `/moe` | Real-time VRAM allocation and PCIe telemetry on Quadro P4200 |
| **P1** | `file_read_chunk` | Both | All | Windowed reading to protect LLM context limits |
| **P1** | `git_diff_inspect` | `qwen2.5-coder:7b` | All | Automated self-review of workspace changes before completion |
| **P2** | `benchmark_inference_speed` | Both | `/moe` | Automated throughput (t/s) and latency profiling |
| **P2** | `sqlite_query` | `qwen3:8b` | `/loom` | Structured state recall from Loom's SQLite storage |
| **P2** | `snapshot_undo` | `qwen3:8b` | `/loom`, `/sysadmin` | Checkpoint creation and rollback for agent actions |
