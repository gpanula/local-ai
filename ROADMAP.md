# Local AI Exploration & Engineering Roadmap

**Workspace**: `~/Projects/local-ai`  
**System Baseline**: NVIDIA Quadro P4200 (8 GB VRAM, Pascal GP104, Compute 6.1)  
**Ollama Endpoint**: `http://127.0.0.1:11434` (Ollama `0.32.13`, CUDA 13.0 API)  
**Date**: August 16, 2026  

---

## 🎯 Core Focus Areas & Objectives

This workspace organizes our local AI research, workflows, and experiments across four primary pillars:

```
                      ┌────────────────────────────────────────┐
                      │    Local AI Engineering Architecture    │
                      └───────────────────┬────────────────────┘
                                          │
        ┌──────────────────┬──────────────┴─────┬──────────────────┐
        ▼                  ▼                    ▼                  ▼
  ┌───────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────┐
  │   Loom    │     │   SysAdmin   │     │     MoE      │     │  Fincept  │
  │  Harness  │     │  & Ansible   │     │ Architecture │     │ Terminal  │
  └───────────┘     └──────────────┘     └──────────────┘     └───────────┘
```

---

## 1. 🧵 Loom Execution Harness (`/loom`)
* **Reference**: [sfw/loom on GitHub](https://github.com/sfw/loom)
* **Purpose**: Desktop and terminal LLM execution harness for complex multi-step workflows with verified execution.
* **Key Architecture & Capabilities**:
  * **Role-Based Routing**: Decomposes work into subtasks; assigns specialized roles (`planner`, `verifier`, `executor`, `extractor`, `compactor`).
  * **Independent Verification**: Separate verifier passes with deterministic checks and multi-tier review before committing changes.
  * **State & Memory**: Uses SQLite for lossless conversation and state recall (`conversation_recall`) instead of lossy summarization.
  * **Fuzzy String Matching & Snapshot Undo**: Resilient to local model formatting quirks, with full before/after snapshot rollbacks.
* **Target Ollama Configuration**:
  * Planner/Verifier: `qwen3:8b`
  * Executor/Extractor: `qwen2.5-coder:7b`

---

## 2. 🐧 Linux SysAdmin, Arc-Orc-Rev Pipeline & Cognitive Learning (`/sysadmin`)
* **Purpose**: Autonomous multi-agent pipeline directing local AI agents to perform Linux systems administration, defensive automation, and iterative self-correction.
* **Key Architecture & Capabilities**:
  * **Arc-Orc-Rev Multi-Agent State Machine (`pipeline.py`)**: 6 canonical horizontal cognitive roles (`architect`, `orchestrator`, `reviewer`, `security`, `coder`, `sysadmin`) adhering to the standard 4-pillar contract (`Analysis`, `Risks`, `Solution`, `Verification`).
  * **Multi-Tier Pre-Execution Code Review Gates**: Zero uninspected execution via Tier 1 Linter (`validator.py`: ShellCheck, AST, path containment), Tier 2A Reviewer Code Gate (`reviewer_code.md`), and Tier 2B Security Behavioral Gate (`security_code.md`).
  * **Multi-Stage Cognitive Memory (`MemoryStore`)**: SQLite-backed FTS5 memory engine with stage-specific guidance, upstream remediation capture (`solved_pattern`), budget exhaustion capture (`hard_failure`), and proactive clean-run mining (`proven_pattern`).
  * **Fine-Tuning Dataset Pipeline (`dataset.py`)**: Trajectories recorded to `sysadmin/data/trajectories.jsonl` and exported to role-targeted Chain-of-Thought (CoT) SFT and DPO datasets.
  * **Live PTY Execution**: Sandboxed interactive bash execution via `terminal-mcp` with full cognitive reasoning visible in stdout and terminal buffers.
* **Recommended Models**:
  * `winter-prime:latest` / `qwen3:8b` (5.2 GB) — Complex multi-step reasoning, architecture, DAG construction, and threat modeling.
  * `winter-coder:8gb-trained` / `qwen2.5-coder:7b` (4.7 GB) — High-fidelity defensive code, ShellCheck compliance, and Ansible engineering.

---

## 3. 🧠 Mixture of Experts (MoE) Exploration (`/moe`)
* **Purpose**: Researching and experimenting with sparse Mixture of Experts architectures under local hardware constraints.
* **Core Concepts**:
  * **Sparse Activation**: Token routing via gating networks to top-$k$ sub-networks (experts), decoupling total parameter size from active per-token compute FLOPs.
  * **Compute vs. Memory**: High parameter capacity running at small-model compute latency, balanced against total weight residency in VRAM/RAM.
  * **Routing Dynamics**: Top-$k$ softmax gating, auxiliary load-balancing loss, shared vs. routed expert models (e.g., DeepSeek MoE).
* **Models to Benchmark**:
  * **100% GPU VRAM**: `olmoe:7b-instruct` (1B active / 7B total, ~3.8 GB) for ultra-fast local routing experimentation.
  * **Hybrid GPU + CPU/RAM Offload**: `mixtral:8x7b` (~26 GB Q4_K_M) or `phi-3.5-moe:16x3.8b` to study partial layer offloading and system RAM bandwidth dynamics.

---

## 4. 📈 FinceptTerminal & Output Validation (`/fincept`)
* **Reference**: [Fincept-Corporation/FinceptTerminal on GitHub](https://github.com/Fincept-Corporation/FinceptTerminal)
* **Purpose**: Exploring the native C++20 / Qt6 financial analytics terminal and using local AI as an independent auditing and validation layer.
* **AI Verification Roles**:
  * **DCF & Valuation Auditing**: Validating WACC calculations, growth assumptions, and sensitivity tables.
  * **Quantitative & Backtest Sanity Checks**: Detecting lookahead bias, overfitting, unrealistic slippage/spreads, and survivorship bias in Python strategies.
  * **Macro & Regulatory Data Auditing**: Cross-referencing extracted SEC 10-K/10-Q numbers and FRED/IMF data points against raw sources.
* **Ollama Integration**: Connecting FinceptTerminal's 37 built-in agents to the local Ollama instance (`http://127.0.0.1:11434`).

---

## 📁 Workspace Directory Structure

```
~/Projects/local-ai/
├── README.md               # Primary project documentation and Graphify setup guide
├── OLLAMA_SUMMARY.md       # Hardware baseline, driver specs, and verified offload metrics
├── ROADMAP.md              # This project roadmap and technical framework
├── graphify-out/           # Generated knowledge graph, HTML maps, callflows, and wiki
├── loom/                   # Loom harness setup, configuration, and runs
├── sysadmin/               # Linux admin workflows, Ansible modules, and test environments
├── moe/                    # MoE benchmarks, routing analysis, and offload tests
└── fincept/                # FinceptTerminal installation, agents config, and audit scripts
```
