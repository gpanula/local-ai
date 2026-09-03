# Incorporating Model Reasoning into Local AI Learning, Memory & Training

## Executive Summary

When local models (`qwen3:8b`, `qwen2.5-coder:7b`, `winter-coder:8gb-trained`) execute tasks via the `mcp_ollama` pipeline, they generate more than just raw shell scripts. They produce structured cognitive traces:
1. **Analysis & Strategy**: Root-cause deconstruction and requirements analysis.
2. **Implementation / Solution**: Native tool calls (`write_file`, `read_file`) and idiomatic code.
3. **Verification & Testing**: Concrete assertion commands, idempotency checks, and regression tests.
4. **Risks & Edge Cases**: Anticipated failure modes, sandbox constraints, and permission boundary caveats.

Previously, these cognitive sections were treated as ephemeral console output and discarded—only the final bash code block was saved to trajectory files and training datasets.

This document defines the architecture to capture, store, and incorporate these reasoning streams across the **four pillars** of our local learning system: Trajectories, Datasets/Fine-Tuning, Memory/Lessons, and Context Injection.

---

## Architecture: Cognitive Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                        User Prompt / Task Spec                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 Local Model Structured Synthesis                       │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 1. Analysis & Strategy (Cognitive Deconstruction)                │  │
│  │ 2. Implementation / Solution (Tool Call / Code)                  │  │
│  │ 3. Verification & Testing (Self-Validation Plan)                 │  │
│  │ 4. Risks & Edge Cases (Proactive Threat Modeling)                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└───────────────────┬───────────────────────────────┬────────────────────┘
                    │                               │
       Approved Execution / Pass        Rework / Failure Loop
                    │                               │
                    ▼                               ▼
    ┌───────────────────────────────┐ ┌──────────────────────────────────┐
    │     Positive Lesson Mining    │ │      Negative Lesson Mining      │
    │   (Pre-emptive risk patterns) │ │   (Reviewer critique extraction) │
    └───────────────┬───────────────┘ └──────────────┬───────────────────┘
                    │                                │
                    ▼                                ▼
    ┌────────────────────────────────────────────────────────────────────┐
    │               MemoryStore (sysadmin/data/memory.db)                │
    │  - Solved patterns, case studies, and verification heuristics      │
    └───────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
    ┌────────────────────────────────────────────────────────────────────┐
    │          Trajectories Store (sysadmin/data/trajectories.jsonl)     │
    │  - Preserves: Full prompt, raw reasoning, code diffs, telemetry    │
    └───────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
    ┌────────────────────────────────────────────────────────────────────┐
    │             Fine-Tuning Dataset Exporter (dataset.py)              │
    │  - CoT SFT: Prompt -> (Analysis + Risks) -> Code -> Verification   │
    │  - CoT DPO: Chosen (Sound logic) vs Rejected (Faulty assumptions)  │
    └────────────────────────────────────────────────────────────────────┘
```

---

## Pillar 1: Trajectory Schema Enhancement (`trajectories.py`)

### Current State
`sysadmin/data/trajectories.jsonl` only stores code strings (`rejected` and `chosen` scripts). When a model corrects itself, we lose *why* it corrected itself.

### Target Schema
Extend `record_trajectory` to record structured reasoning metadata:

```json
{
  "id": "traj-20260902-231500-a1b2c3",
  "timestamp": "2026-09-02T23:15:00Z",
  "task_file": "sysadmin/prompts/hello_world_test.md",
  "prompt": "Write a standalone bash script...",
  "author_model": "winter-coder:8gb-trained",
  "iterations": 1,
  "reasoning": {
    "strategy": "The task requires creating a bash script that meets specific requirements...",
    "risks": "File Overwrite: The script uses overwrite mode... Executable Permissions: The script sets executable permissions...",
    "verification_plan": "1. Check File Existence... 2. Run the Script... 3. Test Error Handling..."
  },
  "chosen": "#!/bin/bash\nset -euo pipefail\n...",
  "rejected": null,
  "telemetry": {
    "eval_count": 459,
    "eval_duration_s": 4.71,
    "tokens_per_second": 97.5,
    "context_tokens": 1085
  }
}
```

---

## Pillar 2: Chain-of-Thought (CoT) Fine-Tuning Datasets (`dataset.py`)

### 1. Supervised Fine-Tuning (SFT) Instruction Tuning
Instead of training the local model to jump straight to raw code, train it to reason explicitly before emitting tool calls or scripts:

* **Format**:
  ```markdown
  ### User:
  <Task Prompt>

  ### Assistant:
  ### Analysis & Strategy
  <Synthesized strategy>

  ### Risks & Edge Cases
  <Anticipated failure modes and constraints>

  ### Implementation
  ```bash
  <Verified code>
  ```

  ### Verification & Testing
  <Verification steps>
  ```

* **Outcome**: Local models fine-tuned with CoT prefixes exhibit lower hallucination rates and significantly better compliance with strict safety directives (such as `set -euo pipefail` and binary path containment).

### 2. Direct Preference Optimization (DPO) Pairs
* **Prompt**: User task specification.
* **Chosen Completion**: Complete response containing sound reasoning, proactive risk mitigation, and verified code.
* **Rejected Completion**: Response exhibiting faulty assumptions, missed sandbox constraints (e.g. attempting to bind ports blocked by seccomp), or lack of error handling.

---

## Pillar 3: Dual-Mode Memory & Lesson Extraction (`extraction.py`)

### Problem
`extraction.py` currently only activates on failure (`_stage_lesson_if_rework`). If a model gets a difficult task right on the first try because it anticipated a subtle edge case, zero lessons are learned.

### Solution: Positive Pattern Extraction (`pre_emptive_defense`)
1. When a task passes on Iteration 1 with code execution verified:
2. Parse the `Risks & Edge Cases` section.
3. If the model identified a domain-specific constraint (e.g., Bubblewrap namespace isolation, socket permission checks, venv path resolution), extract a `proven_pattern` lesson.
4. Store in `MemoryStore` as a high-confidence reference pattern.

---

## Pillar 4: Case-Study Dynamic Prompt Injection (`injection.py`)

### From Flat Rules to Rich Case Studies
Currently, `injection.py` injects static rules:
```markdown
### Relevant Lessons from Memory:
- Always check [ -x "${BIN}" ] before running tools.
```

### Enhanced Injection Format
Inject practical case studies that prime the model's `Analysis & Strategy` phase:
```markdown
### Proven Architectural Patterns from Memory:
- **Scenario**: IPC in Sandboxed Environments
  - **Identified Risk**: Bubblewrap seccomp filters block socket(AF_UNIX) syscalls in user commands.
  - **Mitigation Strategy**: Connect directly to host control sockets from external orchestrators, or fall back to subprocess execution inside the container.
```

---

## Summary of Expected Impact

| Dimension | Before | After |
| :--- | :--- | :--- |
| **Trajectory Value** | Code diffs only | Complete cognitive trace + code + verification |
| **Fine-Tuning Quality** | Raw script completion | Full Chain-of-Thought reasoning + safety modeling |
| **Lesson Memory** | Negative failures only | Dual: Failure corrections + Pre-emptive successes |
| **Model Evolution** | Static execution | Models learn how to think, verify, and defend |
