# Dual-Model Concurrent Residency: 24GB VRAM Architecture & Recommendations

This document outlines the architectural strategy, hardware budget, and operational recommendations for running **two concurrently resident models** on a single 24GB GPU (e.g. NVIDIA GeForce RTX 3090 / RTX 4090) within the Winter Multi-Agent Pipeline.

---

## 1. The 24GB Opportunity: Beyond Single-Model Execution

On workstations equipped with 24GB VRAM, developers typically face a choice:
1. **Run a single large model** (e.g. `winter-prime:24gb` using `qwen2.5-coder:32b`), filling ~20–22 GB of VRAM.
2. **Run two medium/small models simultaneously resident in VRAM** (e.g., a 14B model + an 8B model), sharing the 24GB pool with `keep_alive: -1`.

While a 32B model offers raw per-parameter coding power, running **two concurrently resident models** solves the single greatest vulnerability of autonomous AI software engineering: **Self-Review Bias** ([`plans/arc-orc-rev-pipeline-spec.md` §4.7](file:///home/pang/Projects/local-ai/plans/arc-orc-rev-pipeline-spec.md#L582)).

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                    24GB VRAM Physical Pool (~22.8 GB Usable)                      │
├─────────────────────────────────────────┬─────────────────────────────────────────┤
│        Model 1: Builder / Executor      │       Model 2: Auditor / Gatekeeper     │
│       winter-prime:16gb (14B Q4_K_M)    │             qwen3:8b (8B Q4_K_M)        │
│          VRAM Footprint: ~11.5 GB       │           VRAM Footprint: ~6.2 GB       │
├─────────────────────────────────────────┴─────────────────────────────────────────┤
│  OS / Display Server Overhead: ~1.4 GB  │  Free Headroom / Safety Buffer: ~3.7 GB │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. The "Builder vs. Auditor" Asymmetric Split

When a single model generates code and subsequently reviews its own work, it operates under the same latent weights, training biases, and blind spots. Even under adversarial system prompting, single-model self-audits frequently rubber-stamp subtle logic flaws, unquoted shell variables, or hallucinated APIs.

By loading **two distinct models side-by-side with 0 ms switching latency**, the pipeline establishes true cognitive separation of powers:

```
┌───────────────────────────────────────────────────┐
│           THE BUILDER (winter-prime:16gb)         │
│          qwen2.5-coder:14b (16k context)          │
├───────────────────────────────────────────────────┤
│  • ARCHITECT    (temp: 0.25) -> Modular Design    │
│  • ORCHESTRATOR (temp: 0.10) -> DAG Scheduling    │
│  • CODER        (temp: 0.05) -> Diff Synthesis    │
│  • SYSADMIN     (temp: 0.00) -> Bash Execution    │
└─────────────────────────┬─────────────────────────┘
                          │ Frozen Plan Contract (AnnotatedPlanMessage)
                          ▼
┌───────────────────────────────────────────────────┐
│           THE AUDITOR (qwen3:8b / R1:8b)          │
│            Independent Reasoning Model            │
├───────────────────────────────────────────────────┤
│  • REVIEWER     (temp: 0.00) -> Formal Plan Audit │
│  • SECURITY     (temp: 0.00) -> STRIDE Threat Mod │
└───────────────────────────────────────────────────┘
```

* **The Builder** leverages Qwen2.5-Coder's superior code synthesis, AST editing, and ShellCheck-compliant bash idioms.
* **The Auditor** leverages Qwen3 or DeepSeek-R1's deep chain-of-thought (`<think>`) reasoning to scrutinize the Builder's output without authorial bias.

---

## 3. Dual-Model Architecture Matrix on 24GB GPUs

*Baseline: NVIDIA RTX 3090 (24,576 MB physical VRAM, ~22.5–23.0 GB usable after display server overhead).*

| Architecture Option | Model 1: Builder / Executor | Model 2: Auditor / Gatekeeper | VRAM Allocation | Key Strengths | Best Application |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Option 1: The Balanced Standard**<br>*(⭐ Recommended)* | **`winter-prime:16gb`**<br>(`qwen2.5-coder:14b`, 16k context) | **`qwen3:8b`**<br>(Reviewer prompt, 8k context) | • 14B: ~11.5 GB<br>• 8B: ~6.2 GB<br>• OS: ~1.4 GB<br>**Total: ~19.1 GB**<br>*(~3.7 GB buffer)* | • Complete elimination of self-review bias<br>• High code generation throughput (~35 t/s)<br>• Qwen3 reasoning catches subtle logic/DAG bugs<br>• Comfortable headroom against OOM | **General development, feature implementation, and full pipeline runs** |
| **Option 2: The Adversarial Auditor**<br>*(Maximum Security)* | **`winter-prime:16gb`**<br>(`qwen2.5-coder:14b`, 16k context) | **`deepseek-r1:8b`**<br>(Security/Reviewer, 8k context) | • 14B: ~11.5 GB<br>• R1: ~5.8 GB<br>• OS: ~1.4 GB<br>**Total: ~18.7 GB**<br>*(~4.1 GB buffer)* | • DeepSeek-R1's `<think>` tokens excel at finding edge cases, privilege leaks, and sandbox escapes<br>• Strict enforcement of dry-run rules (R-001/R-002) | **DevOps, sysadmin automation, root-access scripts, security audits** |
| **Option 3: The MoE Algorithmic Pair** | **`deepseek-coder-v2:16b`**<br>(MoE: 2.4B active / 16B total) | **`winter-prime:8gb`**<br>(`qwen2.5-coder:7b`, 16k context) | • MoE: ~12.2 GB<br>• 7B: ~5.8 GB<br>• OS: ~1.4 GB<br>**Total: ~19.4 GB**<br>*(~3.4 GB buffer)* | • DeepSeek-Coder-V2 provides unmatched mathematical reasoning and complex algorithm synthesis<br>• Qwen Prime manages bash execution and DAG dispatch | **Complex math, scientific computing, advanced algorithmic tasks** |
| **Option 4: Deep Context & Cool Thermals** | **`winter-prime:8gb`**<br>(`qwen2.5-coder:7b`, **32k** context) | **`qwen3:8b`**<br>(`qwen3:8b`, **16k** context) | • 7B: ~7.2 GB<br>• 8B: ~7.0 GB<br>• OS: ~1.4 GB<br>**Total: ~15.6 GB**<br>*(~7.2 GB buffer)* | • Massive context window headroom (32k tokens)<br>• Low GPU power draw and fan acoustics (~180W vs 320W)<br>• Never risks VRAM eviction during peak load | **Large codebase indexing, massive refactoring, long documentation epics** |
| **Baseline: Single Heavyweight**<br>*(Alternative Baseline)* | **`winter-prime:24gb`**<br>(`qwen2.5-coder:32b`, 16k context) | *None*<br>(Single resident model) | • 32B: ~20.5 GB<br>• OS: ~1.4 GB<br>**Total: ~21.9 GB**<br>*(~0.9 GB buffer)* | • Highest single-model parameter intelligence (32B coding > 14B coding)<br>• Suffers from self-review bias; no VRAM left for a resident critic | **Single-file high-complexity diffs without automated review loops** |

---

## 4. Deep Dive: Why Option 1 is the Recommended Configuration

For standard day-to-day software engineering, **Option 1 (`winter-prime:16gb` + `qwen3:8b`)** provides the strongest operational balance:

### 1. Complementary Cognitive Profiles
* **`qwen2.5-coder:14b`** is tuned for production software delivery: unified diffs, test assertions, strict JSON schema output, and POSIX shell idioms.
* **`qwen3:8b`** is tuned for analytical scrutiny: detecting inconsistencies between requirements and architecture, challenging missing edge cases, and verifying formal contracts.

### 2. Context Window Allocation
Context window allocation directly consumes VRAM via the KV cache:
* **Builder (`winter-prime:16gb`)**: Pinned to **16,384 tokens** (`PARAMETER num_ctx 16384`). This accommodates large source files, AST trees, and dependency manifests.
* **Auditor (`qwen3:8b`)**: Pinned to **8,192 tokens** (`PARAMETER num_ctx 8192`). The Auditor receives concise, frozen contracts (`AnnotatedPlanMessage`), so 8k context is more than sufficient and preserves ~2 GB of VRAM.

### 3. Safety Margin & Zero Thrashing
* Operating at **~19.1 GB total footprint** leaves a healthy **~3.7 GB safety buffer**.
* This buffer prevents Ollama from ever needing to offload layers to system RAM or PCIe when context windows fill up during long generation runs.

---

## 5. Operational Setup & Ollama Configuration

### Step 1: Ensure Ollama Concurrency Environment Variables
To keep two models concurrently resident in VRAM, Ollama must be configured to permit multi-model residency. 

In your systemd service or environment (`/etc/systemd/system/ollama.service.d/override.conf` or shell):
```ini
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Environment="OLLAMA_NUM_PARALLEL=2"
```

Reload and restart Ollama if modified:
```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### Step 2: Build the Models
Ensure the required customized models are built using [`build_models.sh`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/build_models.sh):
```bash
cd ollama_update/customized_models

# Build the 16GB Prime model (Builder):
./build_models.sh prime-16gb

# Pull base Qwen3 if not already present (Auditor):
ollama pull qwen3:8b
```

### Step 3: Pre-Warm Both Models Into VRAM
To avoid cold-start delays on the first prompt, pre-warm both models with `keep_alive: -1`:
```bash
# Pin Builder in VRAM
curl -s http://127.0.0.1:11434/api/generate -d '{"model": "winter-prime:16gb", "keep_alive": -1}' > /dev/null

# Pin Auditor in VRAM
curl -s http://127.0.0.1:11434/api/generate -d '{"model": "qwen3:8b", "keep_alive": -1}' > /dev/null
```

### Step 4: Verify Residency
Verify that both models are 100% resident in GPU memory:
```bash
ollama ps
```

Expected output:
```text
NAME                 ID              SIZE      PROCESSOR    UNTIL
winter-prime:16gb    a1b2c3d4e5f6    9.0 GB    100% GPU     Forever
qwen3:8b             f6e5d4c3b2a1    5.2 GB    100% GPU     Forever
```

---

## 6. Modelfile Implementation References

* **Builder (16GB Prime)**: [`16gb/Modelfile-prime-qwen14b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/16gb/Modelfile-prime-qwen14b)
* **Auditor Option A (Qwen3 8GB Reviewer)**: [`8gb/Modelfile-reviewer-qwen8b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/8gb/Modelfile-reviewer-qwen8b)
* **Auditor Option B (DeepSeek-R1 8GB Security)**: [`8gb/Modelfile-security-deepseek8b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/8gb/Modelfile-security-deepseek8b)
* **Single-Model Fallback (24GB Prime 32B)**: [`24gb/Modelfile-prime-qwen32b`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/24gb/Modelfile-prime-qwen32b)
* **Model Selection Rationale**: [`WINTER_PRIME_MODEL_SELECTION.md`](file:///home/pang/Projects/local-ai/ollama_update/customized_models/WINTER_PRIME_MODEL_SELECTION.md)
