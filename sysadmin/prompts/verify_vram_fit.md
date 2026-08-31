# Task Specification: Verify Model VRAM Fit & GPU Offload Audit

## Objective
Author and execute a standalone, portable diagnostic Bash script at `sysadmin/verify_vram_fit.sh` that verifies whether a given Ollama model (and its configured context window) fits **100% inside GPU VRAM** or if layers/KV-cache are spilling into system RAM.

---

## 1. Environment & Architectural Constraints
* **Target Script Path**: `sysadmin/verify_vram_fit.sh` (relative to repository root).
* **Virtual Environment & Isolation ([Rule #1](../../AGENTS.md))**:
  * Deterministically resolve `REPO_ROOT` and `VENV_DIR` (`${1:-${REPO_ROOT}/sysadmin/venv}`).
  * Assert required binaries (`ollama`, `nvidia-smi`, `curl`, and `jq` or `${VENV_DIR}/bin/python3`) exist and are executable before running diagnostics.

---

## 2. Functional Diagnostic Protocol

The script must execute the following verification steps:

### Step 1: Model Selection & Baseline Measurement
* Accept an optional model name as an argument (e.g. `winter-orchestrator:24gb`), or default to inspecting the active Winter tier models (`winter-orchestrator:24gb`, `winter-coder:24gb`, `winter-reviewer:24gb`).
* Unload any active models first to obtain a clean, accurate cold baseline.
* Query `nvidia-smi` for baseline GPU VRAM usage and total available VRAM.

### Step 2: Model Warmup & Context Allocation
* Warm up each target model by issuing a short test prompt to initialize model weights and allocate its configured context window (`PARAMETER num_ctx`) in memory.

### Step 3: VRAM Residency & Offload Analysis
* Query Ollama's active model status via `/api/ps` (or `ollama ps`).
* Extract and display the metrics:
  * Total Model Size (`size`)
  * VRAM Allocated (`size_vram`)
  * Configured Context Length (`context_length`)
  * Processor Allocation (`processor`, e.g. `100% GPU` vs `GPU/CPU`)
  * Remaining Free GPU Headroom
* Calculate offload percentage: `((size - size_vram) / size) * 100`.

### Step 4: Diagnostic Reporting & Exit Gates
* **Diagnostic Summary Line**:
  * For each model, print a comprehensive summary line using all extracted metrics:
    `Model: <model> | Context: <context_length> tokens | Processor: <processor> | VRAM: <vram_mb> MB / Total: <size_mb> MB | Free GPU: <free_mb> MB`
* **100% GPU Residency**:
  * If `size_vram == size` (100% GPU), emit:
    `✅ [100% GPU VRAM] Model <model> fits entirely in VRAM with zero CPU offload.`
* **CPU Offload Detected**:
  * If `size_vram < size` or processor shows CPU spill, emit an alert:
    `🚨 [CPU OFFLOAD DETECTED] Model <model> spilled <spill_mb> MB (<spill_pct>%) into System RAM!`
* **Exit Gate**:
  * Exit with code `0` if all evaluated models fit 100% in GPU VRAM with zero CPU offloading.
  * Exit with code `1` if any model offloaded to system RAM.

---

## 3. Defensive Scripting Standards
* Strict mode: `set -euo pipefail`.
* Diagnostic `ERR` trap reporting line number and failed command.
* `EXIT` trap ensuring any test models are cleanly unloaded from VRAM upon completion.
* Zero ShellCheck warnings or errors.
* Guarded success banner: emit `🎉 All tested models fit 100% in GPU VRAM with zero CPU offloading` only when all criteria pass.

---

## 4. Output Contract
The synthesized script must be a complete standalone Bash script starting directly with `#!/bin/bash` at `sysadmin/verify_vram_fit.sh`.
