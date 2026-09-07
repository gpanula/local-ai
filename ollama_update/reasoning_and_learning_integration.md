# Incorporating Model Reasoning into Local AI Learning, Memory & Training

## Executive Summary

When local models (`winter-prime:latest`, `qwen3:8b`, `qwen2.5-coder:7b`) execute tasks across the multi-agent `local-ai` pipeline, they generate more than just raw shell scripts. Across all 6 canonical roles (`architect`, `orchestrator`, `reviewer`, `security`, `coder`, `sysadmin`), they produce structured cognitive traces matching the **4 Pillars of Cognition**:
1. **Analysis & Strategy (Pillar 1)**: Root-cause deconstruction, system architecture, and DAG scheduling rationale.
2. **Risks & Edge Cases (Pillar 2)**: Anticipated failure modes, STRIDE threats, sandbox constraints, and permission boundary caveats.
3. **Solution & Decisions (Pillar 3)**: Formal schema messages (`PlanMessage`, `AnnotatedPlanMessage`), native tool calls (`write_file`), and idiomatic code.
4. **Verification & Testing (Pillar 4)**: Concrete assertion commands, idempotency checks, regression tests, and audit checklists.

This document defines the architecture to capture, store, and incorporate these reasoning streams across the **four pillars** of our local learning system: Trajectories, Datasets/Fine-Tuning, Memory/Lessons, and Context Injection.

---

## Architecture: Cognitive & Learning Flow

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                User Prompt / Task Spec                                 │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Arc-Orc-Rev Planning & Governance Phase                         │
│  ┌────────────────────────┐    ┌────────────────────────┐    ┌──────────────────────┐  │
│  │ 1. Architect (Pillar 1)│ -> │2. Orchestrator(Pillar3)│ -> │ 3. Reviewer (Pillar4)│  │
│  │ (Decompose & System Arch)   │(DAG & Agent Assignment)│    │(Audit & Rubrics Gate)│  │
│  └───────────┬────────────┘    └───────────┬────────────┘    └──────────┬───────────┘  │
│              │ (Revisions)                 │ (Revisions)                │              │
│              └─────────────────────────────┴──────────────┐             │              │
│                                                           │             ▼              │
│                                              ┌────────────┴─────────────────────────┐  │
│                                              │      4. Security Gate (Pillar 2)     │  │
│                                              │      (STRIDE Threat Modeling)        │  │
│                                              └────────────────────┬─────────────────┘  │
└───────────────────────────────────────────────────────────────────┼────────────────────┘
                                                                    │ (Cleared)
                                                                    ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Dispatch & Execution Phase                                │
│  ┌────────────────────────┐    ┌────────────────────────┐    ┌──────────────────────┐  │
│  │ 5. Coder Task Agent    │ -> │ Pre-Execution Gates    │ -> │ 6. Sysadmin Executor │  │
│  │ (write_file synthesis) │    │(Tier1, Tier2A, Tier2B) │    │ (Live terminal execution)│
│  └────────────────────────┘    └────────────────────────┘    └──────────┬───────────┘  │
└─────────────────────────────────────────────────────────────────────────┼──────────────┘
                                                                          │
                        ┌─────────────────────────────────────────────────┴───┐
                        │                                                     │
         Approved Clean Run (0 rev / 0 retries)              Rework / Remediated / Failure
                        │                                                     │
                        ▼                                                     ▼
        ┌───────────────────────────────┐                     ┌───────────────────────────────┐
        │     Positive Lesson Mining    │                     │  Remediation & Failure Mining │
        │ (Cognition risks -> proven)   │                     │ (Critique -> solved_pattern / │
        │ (Planning utility attribution)│                     │  Budget -> hard_failure)      │
        └───────────────┬───────────────┘                     └───────────────┬───────────────┘
                        │                                                     │
                        └───────────────────────┬─────────────────────────────┘
                                                │
                                                ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │                    MemoryStore (sysadmin/data/memory.db)                    │
        │ - Solved patterns, proven patterns, hard failures, and dynamic rubrics     │
        └───────────────────────────────────────┬─────────────────────────────────────┘
                                                │
                                                ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │              Trajectories Store (sysadmin/data/trajectories.jsonl)          │
        │ - Full multi-agent cognition traces, roles, script versions, diffs, outcome │
        └───────────────────────────────────────┬─────────────────────────────────────┘
                                                │
                                                ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │                  Fine-Tuning Dataset Exporter (dataset.py)                  │
        │ - CoT SFT: Prompt -> (Analysis + Risks) -> Code -> Verification             │
        │ - CoT DPO: Chosen (Sound logic) vs Rejected (Faulty assumptions)            │
        └─────────────────────────────────────────────────────────────────────────────┘
```

---

## Pillar 1: Trajectory Schema Enhancement (`trajectories.py`)

### Target Schema
`sysadmin/data/trajectories.jsonl` stores complete multi-agent pipeline runs with full cognitive transparency:

```json
{
  "id": "traj-20260907-184412-f5336b",
  "timestamp": "2026-09-07T18:44:12+00:00",
  "task_file": "runs/run-fin-test/state.json",
  "canonical_category": "Multi-Agent Orchestration",
  "prompt": "Write a standalone script that...",
  "author_model": "winter-prime:latest",
  "injected_lessons": ["lesson-arch-01", "lesson-orc-01"],
  "reviewer_critique": "",
  "iterations": 1,
  "outcome": "approved",
  "roles": {
    "architect": {
      "model": "winter-prime:latest",
      "analysis": "Deconstruct task into creation and execution components...",
      "risks": "Potential race conditions in file creation...",
      "solution": "Generate PlanMessage with decoupled tasks...",
      "verification": "Assert valid task ids and domain tags..."
    },
    "orchestrator": {
      "model": "winter-prime:latest",
      "analysis": "Map dependencies between coder and sysadmin...",
      "risks": "Cyclic dependencies in DAG...",
      "solution": "Annotate plan with linear edge t-001 -> t-002...",
      "verification": "Topological sort assertion..."
    },
    "reviewer": {
      "model": "winter-prime:latest",
      "analysis": "Audit DAG and task tools against registry...",
      "risks": "Unsafe command execution...",
      "solution": "Approve annotated plan...",
      "verification": "Check against audit_heuristics..."
    },
    "security": {
      "model": "winter-prime:latest",
      "analysis": "STRIDE threat modeling...",
      "risks": "Path traversal or privilege escalation...",
      "solution": "Clear plan...",
      "verification": "Enforce workspace boundary..."
    }
  },
  "chosen": "#!/bin/bash\nset -euo pipefail\n...",
  "rejected": null,
  "payload_type": "inline"
}
```

---

## Pillar 2: Chain-of-Thought (CoT) Fine-Tuning Datasets (`dataset.py`)

### 1. Supervised Fine-Tuning (SFT) Instruction Tuning
Models are trained to reason explicitly across the 4 pillars before emitting structured messages or scripts:

* **Format**:
  ```markdown
  ### User:
  <Task Prompt>

  ### Assistant:
  ### Analysis & Strategy
  <Deconstruction, requirements analysis, system topology>

  ### Risks & Edge Cases
  <Anticipated failure modes, STRIDE threats, sandboxing constraints>

  ### Implementation / Solution
  ```bash
  <Verified code or JSON message>
  ```

  ### Verification & Testing
  <Idempotency assertions, unit tests, regression commands>
  ```

* **Outcome**: Local models fine-tuned with CoT prefixes exhibit lower hallucination rates and significantly better compliance with safety standards (`set -euo pipefail`, deterministic binary paths).

### 2. Direct Preference Optimization (DPO) Pairs
* **Prompt**: User task specification or stage input.
* **Chosen Completion**: Full response containing sound reasoning, proactive risk mitigation, and verified code.
* **Rejected Completion**: Response exhibiting faulty assumptions, missed sandbox constraints (e.g. attempting to bind ports blocked by seccomp), or lack of error handling.

---

## Pillar 3: Multi-Stage Memory & Lesson Extraction (`extraction.py`, `pipeline.py`)

Lesson extraction operates reactively across every stage of the state machine:

### 1. Upstream Planning Remediation (`solved_pattern`)
- **Trigger**: When Reviewer or Security rejects an initial plan (`architect_revisions_used > 0` or `orchestrator_revisions_used > 0`), and a subsequent revision clears the Security Gate.
- **Action**: Extracts the critique from the verdict and the remediated plan via `extract_lesson_from_critique`. Stages a `solved_pattern` lesson in `MemoryStore`.

### 2. Planning Budget Exhaustion (`hard_failure`)
- **Trigger**: When Architect or Orchestrator exhausts its revision budget (3 attempts) without clearing review.
- **Action**: Stages a `hard_failure` lesson documenting the unresolvable planning conflict, abort reason, and original prompt.

### 3. Dispatch Rework & Task Failures
- **Trigger**: Intra-run task execution failure.
- **Action**: Injects `cognition.risks` into the immediate retry of that task (`retries < 2`). If retries exhaust, extracts a negative lesson to `MemoryStore`.

### 4. Proactive Risk Mitigation Mining (`proven_pattern`)
- **Trigger**: Clean pipeline execution (0 revisions, 0 task retries, status `complete`).
- **Action**: Mines the proactive threat mitigations from `cognition.risks` and `cognition.solution` into a `proven_pattern` lesson.

### 5. Clean Planning Lesson Attribution
- **Trigger**: Clean plan clearance (0 revisions).
- **Action**: Credits utility (+1 `prevented_rework_count`) to all planning lessons injected into Architect, Orchestrator, Reviewer, and Security.

---

## Pillar 4: Case-Study Dynamic Prompt Injection (`injection.py`, `pipeline.py`)

Lessons are retrieved dynamically and injected into each role:
- **Architect**: Injected under `user_payload["architectural_guidance"]`.
- **Orchestrator**: Injected under `user_payload["orchestration_guidance"]`.
- **Reviewer**: Injected as dynamic verification rules into `annotated_plan["audit_heuristics"]`.
- **Security**: Injected as threat heuristics into `annotated_plan["security_heuristics"]`.
- **Executors (`coder`, `sysadmin`)**: Formatted as case studies and injected into `TaskMessage.description`.

---

## Summary of Impact

| Dimension | Before | After |
| :--- | :--- | :--- |
| **Trajectory Scope** | Executor code diffs only | Full multi-agent cognitive traces across all 6 roles |
| **Memory Coverage** | Dispatch executor only | Comprehensive: Architect, Orchestrator, Reviewer, Security, Coder, Sysadmin |
| **Extraction Triggers** | Negative executor rework only | Full lifecycle: Upstream remediation, budget exhaustion, task retry, proactive clean run mining |
| **Verification Rubrics** | Static hardcoded prompts | Dynamic heuristics injected from verified memory |
