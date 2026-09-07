# Why Qwen2.5-Coder Powers Winter Prime: Model Selection & Architectural Rationale

This document details the architectural requirements, empirical trade-offs, and hardware constraints that guided the selection of Alibaba Cloud's **`qwen2.5-coder`** family (`7b`, `14b`, `32b`) as the foundation engine for **Winter Prime** across all local GPU tiers.

---

## 1. Executive Summary & Problem Context

**Winter Prime** is the foundational engine for our **Single-Model Multi-Persona (SMMP)** execution mode (defined in [`plans/arc-orc-rev-pipeline-spec.md` §4.7](file:///home/pang/Projects/local-ai/plans/arc-orc-rev-pipeline-spec.md#L534)).

In standard multi-agent setups, distinct models are swapped into GPU memory per stage (e.g., DeepSeek for planning, Codestral for coding, Mistral for review). On consumer and single-workstation GPUs (8GB–24GB VRAM), this causes:
* **Severe Model-Swapping Latency**: 2 to 10 seconds of PCIe/RAM thrashing per transition, compounding to 30–90 seconds of idle overhead per pipeline run.
* **VRAM Fragmentation & OOM Risk**: Repeated allocation and deallocation across different model architectures destabilizes Ollama memory management under tight budgets.

Winter Prime solves this by pinning a single foundation model in GPU memory (`keep_alive: -1`) and dynamically shifting cognitive roles with **0 ms model-loading latency**. 

However, this architecture places extreme demands on the underlying model: **one single model must reliably execute all six canonical roles without degrading in either high-level conceptual planning or low-level syntactic execution.**

```
                        ┌────────────────────────────────────────────────────────┐
                        │        Resident Foundation Model (VRAM-Pinned)         │
                        │           qwen2.5-coder (keep_alive: -1)               │
                        └───────────────────────────┬────────────────────────────┘
                                                    │
                 ┌──────────────────────────────────┼──────────────────────────────────┐
                 ▼                                  ▼                                  ▼
           [ ARCHITECT ]                      [ REVIEWER ]                      [ SYSADMIN ]
           • Scope: Decomposition             • Scope: Formal plan audit        • Scope: Defensive bash
           • Temp: 0.25 (exploratory)         • Temp: 0.00 (deterministic)      • Temp: 0.00 (zero-hallucination)
           • Schema: PlanMessage              • Schema: ReviewVerdict           • Schema: Script Execution
```

---

## 2. The Multi-Persona Challenge: The 6 Canonical Roles

A candidate model for Winter Prime must satisfy conflicting cognitive postures:

| Role | Cognitive Focus | Required Model Capabilities | Failure Modes of Typical Models |
| :--- | :--- | :--- | :--- |
| **1. Architect** | System decomposition, modularity, task graphs | Broad conceptual reasoning, API design, trade-off analysis | Code-only models produce Python snippets instead of architecture specs |
| **2. Orchestrator** | Topological sorting, DAG scheduling | Strict JSON formatting, dependency logic, boundary discipline | Conversational models emit chat wrappers around JSON |
| **3. Reviewer** | Adversarial auditing, formal verification | Skepticism, rule compliance, schema verification | Models suffer "self-review bias" and rubber-stamp flawed plans |
| **4. Security Gate** | STRIDE threat modeling, sandbox validation | Defensive paranoia, permission inspection, CVE awareness | General models miss command injection, privilege leakage, or unquoted variables |
| **5. Coder** | Code synthesis, unified diffs, AST editing | Zero conversational boilerplate, clean diff generation, test assertions | Verbose models pollute stdout; generate broken patch offsets |
| **6. Sysadmin** | Infrastructure, systemd, Ansible, Bash | ShellCheck compliance, POSIX / Bash standards (`set -euo pipefail`, trap handling) | Models hallucinate non-existent CLI flags, unquoted heredocs, or insecure one-liners |

Most open-weights models are polarized: they are either **chat/reasoning generalists** (strong in Roles 1–4, weak in 5–6) or **code-completion engines** (strong in Role 5, weak in 1–4 and 6).

`qwen2.5-coder` was chosen because it bridges this cognitive divide.

---

## 3. The Five Core Selection Pillars

### Pillar 1: Dual Cognitive Competence (Conceptual Reasoning + Code Mastery)
Qwen2.5-Coder was pretrained on massive web text, mathematics, synthetic reasoning chains, and over 5.5 trillion tokens of code across 128 languages. Unlike pure code-completion models that falter at abstract logic, Qwen2.5-Coder demonstrates reasoning benchmarks on par with top general chat models (e.g. Qwen2.5 base and Llama 3.1) while maintaining top-of-class HumanEval and SWE-bench performance. It designs systems as well as it writes code.

### Pillar 2: Symmetric Hardware Tier Scaling (7B / 14B / 32B Trinity)
Consumer hardware is divided into three common VRAM envelopes: **8GB**, **16GB**, and **24GB**.
Very few high-performance model families offer clean, identically trained models at all three thresholds:

| Workstation Tier | Available VRAM | Selected Model | Quantization | Context Window | VRAM Footprint | Modelfile |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 🟢 **8GB Tier** | ~5.0–6.5 GB | `qwen2.5-coder:7b` | Q4_K_M | 16k (`16384`) | ~5.6–6.2 GB | [`Modelfile-prime-qwen7b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/8gb/Modelfile-prime-qwen7b) |
| 🟡 **16GB Tier** | ~10–14 GB | `qwen2.5-coder:14b` | Q4_K_M | 32k (`32768`) | ~10.5–13.2 GB | [`Modelfile-prime-qwen14b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/16gb/Modelfile-prime-qwen14b) |
| 🟣 **24GB Tier** | ~18–22 GB | `qwen2.5-coder:32b` | Q4_K_M | 16k (`16384`) | ~19.5–21.8 GB | [`Modelfile-prime-qwen32b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/24gb/Modelfile-prime-qwen32b) |

This symmetry ensures that prompting strategies, schema contracts, and sampling parameters remain **100% portable** across workstations. Developers can test workflows on an 8GB laptop and deploy the exact same pipeline to a 24GB workstation.

### Pillar 3: Strict Schema Discipline & Structured JSON
Winter Prime communicates across pipeline stages via strict Pydantic schemas:
* `PlanMessage` (Architect -> Orchestrator)
* `AnnotatedPlanMessage` (Orchestrator -> Reviewer)
* `ReviewVerdict` (Reviewer -> Orchestrator)
* `SecurityVerdict` (Security -> Pipeline Dispatcher)

Qwen2.5-Coder exhibits exceptional compliance with system-level formatting instructions. Under `temperature: 0.0`, it consistently emits raw valid JSON without conversational prefaces ("Here is the plan:"), markdown code blocks, or postscript explanations.

### Pillar 4: DevOps & Defensive Bash Fluency
The **Sysadmin** role requires uncompromising adherence to defensive shell scripting standards (enforced by `AGENTS.md` and ShellCheck):
* Mandatory `set -euo pipefail`
* Deterministic error traps (`trap '...' ERR`)
* Quoted heredoc delimiters (`cat <<'EOF'`) to prevent premature SC2154 expansion
* FQCN Ansible tasks and idempotency assertions

Many open models fail these invariants by defaulting to naive `echo` loops or non-portable bash syntax. Qwen2.5-Coder's pretraining corpus included extensive DevOps repositories, Dockerfiles, and CI/CD pipelines, giving it an instinctive grasp of POSIX and defensive bash conventions.

### Pillar 5: Dynamic Controllability via Sampling Dials
Winter Prime modulates four runtime parameters per stage:
1. **Stateless Context Reset** (fresh `[system, user]` pair to eliminate cross-role contamination)
2. **Role Persona Conditioning** (`sysadmin/prompts/roles/{role}.md`)
3. **Sampling Profile Tuning** (`temperature`, `top_p`)
4. **Tool Registry Masking** (physical tool confinement)

Qwen2.5-Coder responds predictably to temperature tuning:
* `temperature: 0.25`: Generates modular, divergent architecture alternatives for the Architect.
* `temperature: 0.10`: Formulates deterministic, acyclic DAG schedules for the Orchestrator.
* `temperature: 0.00`: Enforces greedy, adversarial auditing for Reviewer and Security Gate.

---

## 4. Comprehensive Alternatives Evaluation Matrix

The following matrix compares candidate open-weights models against the requirements of Winter Prime:

| Candidate Family | Parameter Sizes | Tier Fit | Reasoning & Architecture | Code & Diff Synthesis | Bash / Sysadmin | Strict JSON Conformance | Multi-Persona Verdict |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **`qwen2.5-coder`** *(Chosen)* | 7B, 14B, 32B | 🟢 8GB<br>🟡 16GB<br>🟣 24GB | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **Selected Default**<br>Best balance of reasoning, code, bash, and symmetric hardware scaling. |
| **`qwen3:8b`** | 8B | 🟢 8GB | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | **Excellent Specialist**<br>Superior CoT and root-cause analysis, but lacks 14B/32B tier siblings and is more verbose for code diffs. Dedicated 8GB Reviewer. |
| **`deepseek-coder-v2:16b`** | 16B (MoE, 2.4B active) | 🟡 16GB<br>🟣 24GB | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **Strong Alternative for 16GB+**<br>High algorithmic synthesis, but lacks a 7B variant for 8GB GPUs, and 236B is too large for local workstations. |
| **`codestral:22b`** | 22B | 🟣 24GB | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **Top Code Generator**<br>Superb multi-language code generation, but too large for 8GB/16GB, weaker on abstract DAG planning, and has non-commercial license constraints. |
| **`deepseek-r1-distill-qwen`** | 8B, 14B, 32B | 🟢 8GB<br>🟡 16GB<br>🟣 24GB | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **Auditing Specialist**<br>Incredible deep `<think>` reasoning for security and review, but slow generation velocity and verbose output make it unsuitable for high-throughput code synthesis. |
| **`llama-3.1` / `llama-3.3`** | 8B, 70B | 🟢 8GB<br>*(70B needs 48GB+)* | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | **Missing Mid-Tier**<br>Great general reasoning, but jumps from 8B to 70B (leaving 16GB and 24GB unoptimized); 8B coding trails Qwen2.5-Coder 7B. |
| **`starcoder2`** | 7B, 15B | 🟢 8GB<br>🟡 16GB | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **Unsuitable for SMMP**<br>Strong raw code completion, but lacks instruction-following depth for high-level multi-role personas and JSON DAG generation. |
| **`phi-4`** | 14B | 🟡 16GB | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **Isolated Sizing**<br>Strong math and synthetic reasoning, but no 7B or 32B equivalents for hardware tier portability. |

---

## 5. Deep-Dive: Qwen2.5-Coder vs. Key Competitors

### Why not `qwen3:8b` as the Prime default?
`qwen3:8b` is already installed locally and serves as our dedicated Reviewer model in the 8GB multi-model suite ([`Modelfile-reviewer-qwen8b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/8gb/Modelfile-reviewer-qwen8b)). It possesses deeper general reasoning and native thinking tokens than `qwen2.5-coder:7b`.

However, for a **universal single-model runner**:
1. **Coding Conciseness**: `qwen3` tends to surround code in discursive explanations, whereas `qwen2.5-coder` emits compact unified diffs and pure scripts required by automated execution tools.
2. **Token Generation Latency**: `qwen3` spends internal tokens reasoning through simple instructions (~27 tokens/s effective throughput vs. ~40+ tokens/s on `qwen2.5-coder`).
3. **No 14B / 32B Siblings**: `qwen3` currently lacks the full 14B and 32B family in the local distribution, breaking the 16GB and 24GB hardware tier parity.

### Why not `codestral:22b` as the Prime default?
Codestral is one of the world's best code-generation models, and is used in our 24GB specialized tier for Sysadmin, Security, and Reviewer. However:
1. **VRAM Footprint**: At 22B parameters, Codestral requires ~14–18 GB VRAM. It cannot run on the 8GB tier at all, and leaves zero headroom for context on 16GB cards.
2. **DAG Planning**: In empirical testing, Codestral occasionally stumbles on complex multi-task topological dependency matrices compared to Qwen 32B.

---

## 6. Modelfile Implementation References

The Winter Prime modelfiles applying this architecture are located in:
* **8GB Tier**: [`8gb/Modelfile-prime-qwen7b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/8gb/Modelfile-prime-qwen7b) (`winter-prime:8gb-qwen`, `winter-prime:8gb`, `winter-prime:latest`)
* **16GB Tier**: [`16gb/Modelfile-prime-qwen14b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/16gb/Modelfile-prime-qwen14b) (`winter-prime:16gb-qwen`, `winter-prime:16gb`)
* **24GB Tier**: [`24gb/Modelfile-prime-qwen32b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/24gb/Modelfile-prime-qwen32b) (`winter-prime:24gb-qwen`, `winter-prime:24gb`)

All three modelfiles embed the **Standard 4-Pillar Contract** (Analysis & Strategy, Risks & Edge Cases, Solution / Implementation, Verification & Testing) and universal defensive coding invariants into the base `qwen2.5-coder` image.
