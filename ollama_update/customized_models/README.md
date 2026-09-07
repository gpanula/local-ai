# Winter AI — Customized Ollama Modelfiles

The **Winter** model family defines specialized system prompts, pinned context windows, and sampling parameters tailored for autonomous multi-agent software engineering across three hardware tiers:

- **🟢 8GB Tier (`8gb/`)**: Consumer laptops and workstations (Target: ~5.0–6.5 GB VRAM)
- **🟡 16GB Tier (`16gb/`)**: Mid-range workstations and GPUs (Target: ~10–14 GB VRAM)
- **🟣 24GB Tier (`24gb/`)**: High-end compute nodes and server GPUs (Target: ~16–22 GB VRAM)

---

## 📦 Base Models & Pre-Pull Commands

The Winter suite relies on 7 underlying open-weights models from the Ollama library. You can pull them ahead of time before running the build scripts:

### 🟢 8GB Tier Base Models (~14.2 GB disk)
```bash
ollama pull qwen2.5-coder:7b
ollama pull qwen3:8b
ollama pull deepseek-r1:8b
```

### 🟡 16GB Tier Base Models (~16.7 GB disk)
```bash
ollama pull qwen2.5-coder:14b
ollama pull deepseek-coder-v2:16b
```

### 🟣 24GB Tier Base Models (~30.2 GB disk)
```bash
ollama pull qwen2.5-coder:32b
ollama pull codestral:latest
```

### ⚡ Pre-Pull All Base Models (One-Liner)
```bash
ollama pull qwen2.5-coder:7b && \
ollama pull qwen3:8b && \
ollama pull deepseek-r1:8b && \
ollama pull qwen2.5-coder:14b && \
ollama pull deepseek-coder-v2:16b && \
ollama pull qwen2.5-coder:32b && \
ollama pull codestral:latest
```

---

## 🏛️ The 6 Core Roles

| Role | Responsibility | Key Standards & Prompt Invariants |
| :--- | :--- | :--- |
| **`orchestrator`** | Planning & task decomposition | Breaks complex epics into DAG phases, writes Rule 8 prompt specs, assigns roles |
| **`architect`** | System & harness design | Python, async/asyncio, Pydantic, deterministic state machine recovery |
| **`coder`** | Code synthesis & editing | Deterministic AST output, unified diffs, zero conversational boilerplate |
| **`sysadmin`** | Infrastructure & DevOps | Strict Bash (`set -euo pipefail`, `ERR` traps), Ansible idempotency & linting |
| **`security`** | Security audit & hardening | OWASP/CWE, privilege leakage, credential exposure, concurrency race checks |
| **`reviewer`** | Code review & acceptance | Prompt compliance, acceptance gates, structured verdicts (`APPROVED` / `REVISION_REQUESTED`) |

---

## 🟢 8GB VRAM Tier (`8gb/`)

| Role | Tag (Engine) | Default Alias | Base Model | Modelfile | Context |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`orchestrator`** | `winter-orchestrator:8gb-deepseek` | `winter-orchestrator:8gb` | `deepseek-r1:8b` | [`8gb/Modelfile-orchestrator-deepseek8b`](8gb/Modelfile-orchestrator-deepseek8b) | 16k (`16384`) |
| **`architect`** | `winter-architect:8gb-qwen` | `winter-architect:8gb` | `qwen2.5-coder:7b` | [`8gb/Modelfile-architect-qwen7b`](8gb/Modelfile-architect-qwen7b) | 16k (`16384`) |
| **`coder`** | `winter-coder:8gb-qwen` | `winter-coder:8gb` | `qwen2.5-coder:7b` | [`8gb/Modelfile-coder-qwen7b`](8gb/Modelfile-coder-qwen7b) | 16k (`16384`) |
| **`sysadmin`** | `winter-sysadmin:8gb-qwen` | `winter-sysadmin:8gb` | `qwen2.5-coder:7b` | [`8gb/Modelfile-sysadmin-qwen7b`](8gb/Modelfile-sysadmin-qwen7b) | 16k (`16384`) |
| **`security`** | `winter-security:8gb-deepseek` | `winter-security:8gb` | `deepseek-r1:8b` | [`8gb/Modelfile-security-deepseek8b`](8gb/Modelfile-security-deepseek8b) | 16k (`16384`) |
| **`reviewer`** | `winter-reviewer:8gb-qwen` | `winter-reviewer:8gb` | `qwen3:8b` | [`8gb/Modelfile-reviewer-qwen8b`](8gb/Modelfile-reviewer-qwen8b) | 8k (`8192`) |
| **⚡ `SMMP (All Roles)`** | `winter-smmp:8gb-qwen` | `winter-smmp:8gb`, `winter-smmp:latest` | `qwen2.5-coder:7b` | [`8gb/Modelfile-smmp-qwen7b`](8gb/Modelfile-smmp-qwen7b) | 16k (`16384`) |

---

## 🟡 16GB VRAM Tier (`16gb/`)

| Role | Tag (Engine) | Default Alias | Base Model | Modelfile | Context |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`orchestrator`** | `winter-orchestrator:16gb-deepseek` | `winter-orchestrator:16gb` | `deepseek-coder-v2:16b` | [`16gb/Modelfile-orchestrator-deepseek16b`](16gb/Modelfile-orchestrator-deepseek16b) | 32k (`32768`) |
| **`architect`** | `winter-architect:16gb-deepseek` | `winter-architect:16gb` | `deepseek-coder-v2:16b` | [`16gb/Modelfile-architect-deepseek16b`](16gb/Modelfile-architect-deepseek16b) | 32k (`32768`) |
| **`coder`** | `winter-coder:16gb-qwen` | `winter-coder:16gb` | `qwen2.5-coder:14b` | [`16gb/Modelfile-coder-qwen14b`](16gb/Modelfile-coder-qwen14b) | 32k (`32768`) |
| **`sysadmin`** | `winter-sysadmin:16gb-qwen` | `winter-sysadmin:16gb` | `qwen2.5-coder:14b` | [`16gb/Modelfile-sysadmin-qwen14b`](16gb/Modelfile-sysadmin-qwen14b) | 32k (`32768`) |
| **`security`** | `winter-security:16gb-deepseek` | `winter-security:16gb` | `deepseek-coder-v2:16b` | [`16gb/Modelfile-security-deepseek16b`](16gb/Modelfile-security-deepseek16b) | 32k (`32768`) |
| **`reviewer`** | `winter-reviewer:16gb-deepseek` | `winter-reviewer:16gb` | `deepseek-coder-v2:16b` | [`16gb/Modelfile-reviewer-deepseek16b`](16gb/Modelfile-reviewer-deepseek16b) | 32k (`32768`) |
| **⚡ `SMMP (All Roles)`** | `winter-smmp:16gb-qwen` | `winter-smmp:16gb` | `qwen2.5-coder:14b` | [`16gb/Modelfile-smmp-qwen14b`](16gb/Modelfile-smmp-qwen14b) | 32k (`32768`) |

---

## 🟣 24GB VRAM Tier (`24gb/`)

| Role | Tag (Engine) | Default Alias | Base Model | Modelfile | Context |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`orchestrator`** | `winter-orchestrator:24gb-qwen` | `winter-orchestrator:24gb` | `qwen2.5-coder:32b` | [`24gb/Modelfile-orchestrator-qwen32b`](24gb/Modelfile-orchestrator-qwen32b) | 16k (`16384`) |
| **`architect`** | `winter-architect:24gb-qwen` | `winter-architect:24gb` | `qwen2.5-coder:32b` | [`24gb/Modelfile-architect-qwen32b`](24gb/Modelfile-architect-qwen32b) | 16k (`16384`) |
| **`coder`** | `winter-coder:24gb-qwen` | `winter-coder:24gb` | `qwen2.5-coder:32b` | [`24gb/Modelfile-coder-qwen32b`](24gb/Modelfile-coder-qwen32b) | 16k (`16384`) |
| **`sysadmin`** | `winter-sysadmin:24gb-codestral` | `winter-sysadmin:24gb` | `codestral:latest` | [`24gb/Modelfile-sysadmin-codestral`](24gb/Modelfile-sysadmin-codestral) | 32k (`32768`) |
| **`security`** | `winter-security:24gb-codestral` | `winter-security:24gb` | `codestral:latest` | [`24gb/Modelfile-security-codestral`](24gb/Modelfile-security-codestral) | 32k (`32768`) |
| **`reviewer`** | `winter-reviewer:24gb-codestral` | `winter-reviewer:24gb` | `codestral:latest` | [`24gb/Modelfile-reviewer-codestral`](24gb/Modelfile-reviewer-codestral) | 32k (`32768`) |
| **⚡ `SMMP (All Roles)`** | `winter-smmp:24gb-qwen` | `winter-smmp:24gb` | `qwen2.5-coder:32b` | [`24gb/Modelfile-smmp-qwen32b`](24gb/Modelfile-smmp-qwen32b) | 16k (`16384`) |

---

## ⚡ Single-Model Multi-Persona (SMMP) Mode

In addition to the 18 specialized single-role models, Winter provides **SMMP foundation models** for high-throughput single-GPU workstations. A single model remains resident in VRAM (`keep_alive: -1`) and shifts personas across all 6 roles with **0 ms model loading latency**:

- **`winter-smmp:8gb`**: Qwen2.5-Coder 7B, 16k context (Target: ~5.6–6.5 GB VRAM)
- **`winter-smmp:16gb`**: Qwen2.5-Coder 14B, 32k context (Target: ~10–14 GB VRAM)
- **`winter-smmp:24gb`**: Qwen2.5-Coder 32B, 16k context (Target: ~18–22 GB VRAM)

---

## 🚀 Building Models with `build_models.sh`

A unified build script is provided to create and alias all models for a specific tier, SMMP mode, or the entire suite:

```bash
cd ollama_update/customized_models

# Pull base models for 8GB tier:
./build_models.sh pull-8gb

# Build 8GB SMMP foundation model:
./build_models.sh smmp-8gb

# Build 16GB SMMP foundation model:
./build_models.sh smmp-16gb

# Build 24GB SMMP foundation model:
./build_models.sh smmp-24gb

# Build all SMMP foundation models:
./build_models.sh smmp

# Build all 6 specialized models for 8GB tier:
./build_models.sh 8gb

# Build all 6 specialized models for 16GB tier:
./build_models.sh 16gb

# Build all 6 specialized models for 24GB tier:
./build_models.sh 24gb

# Pull all base models and build all specialized tiers (18 models):
./build_models.sh pull-all
./build_models.sh all

# List all available models & aliases:
./build_models.sh list
```
