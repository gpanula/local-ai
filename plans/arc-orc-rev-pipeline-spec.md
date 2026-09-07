# Arc-Orc-Rev Pipeline — Formal Specification (v7)

> **Status**: Draft / RFC (v7)  
> **Workspace**: `~/Projects/local-ai`  
> **Alignment**: [sysadmin/README.md](../sysadmin/README.md) — Horizontal Cognitive Taxonomy & 4-Pillar Contract  
> **Relates to**: [ROADMAP.md](../ROADMAP.md), [taxonomy.json](../ollama_update/taxonomy.json)

---

## Table of Contents

- [1. Foundational Alignment](#1-foundational-alignment)
  - [1.1 Vertical Domain Taxonomy (task classification)](#11-vertical-domain-taxonomy-task-classification)
  - [1.2 Horizontal Cognitive Taxonomy — The 6 Roles](#12-horizontal-cognitive-taxonomy--the-6-roles)
  - [1.3 Standard 4-Pillar Contract](#13-standard-4-pillar-contract)
- [2. Updated Pipeline Flow](#2-updated-pipeline-flow)
- [3. Message Schemas (v2 — 4-Pillar Aligned)](#3-message-schemas-v2--4-pillar-aligned)
  - [3.1 `Cognition` Block (embedded in every message)](#31-cognition-block-embedded-in-every-message)
  - [3.2 `PlanMessage` (Architect → Orchestrator)](#32-planmessage-architect--orchestrator)
  - [3.3 `AnnotatedPlanMessage` (Orchestrator → Reviewer)](#33-annotatedplanmessage-orchestrator--reviewer)
  - [3.4 `ReviewVerdict` (Reviewer → next agent)](#34-reviewverdict-reviewer--next-agent)
  - [3.5 `SecurityVerdict` (Security Gate → Orchestrator or Architect)](#35-securityverdict-security-gate--orchestrator-or-architect)
  - [3.6 `TaskMessage` (Orchestrator → Executor)](#36-taskmessage-orchestrator--executor)
  - [3.7 `ExecutionResult` (Executor → Orchestrator)](#37-executionresult-executor--orchestrator)
- [4. Agent Contracts (6-Role Aligned)](#4-agent-contracts-6-role-aligned)
  - [4.1 Architect *(Role: Architect)*](#41-architect-role-architect)
  - [4.2 Orchestrator *(Role: Orchestrator)*](#42-orchestrator-role-orchestrator)
  - [4.3 Reviewer *(Role: Reviewer)*](#43-reviewer-role-reviewer)
  - [4.4 Security Gate *(Role: Security)*](#44-security-gate-role-security)
  - [4.5 Executor: Coder *(Role: Coder)*](#45-executor-coder-role-coder)
  - [4.6 Executor: Sysadmin *(Role: Sysadmin)*](#46-executor-sysadmin-role-sysadmin)
  - [4.7 Single-Model Multi-Persona (SMMP) Execution Profile](#47-single-model-multi-persona-smmp-execution-profile)
- [5. Loop Conditions & Exit Rules](#5-loop-conditions--exit-rules)
  - [5.1 Feedback Loop Matrix](#51-feedback-loop-matrix)
  - [5.2 Budget Exhaustion & Human Escalation Checkpoints](#52-budget-exhaustion--human-escalation-checkpoints)
  - [5.3 Identical Plan Detection (Anti-Loop Guard)](#53-identical-plan-detection-anti-loop-guard)
  - [5.4 Executor Failure Handling (Inner Loop & Recovery Governance)](#54-executor-failure-handling-inner-loop--recovery-governance)
- [6. State & Persistence](#6-state--persistence)
  - [6.1 Run State (external, by `run_id`)](#61-run-state-external-by-run_id)
  - [6.2 Continuous Learning Hooks & Lesson Timing Policy](#62-continuous-learning-hooks--lesson-timing-policy)
- [7. Registries](#7-registries)
  - [7.1 Tool Registry (`sysadmin/data/registries/tools.json`)](#71-tool-registry-sysadmindataregistriestoolsjson)
  - [7.2 Agent Registry (`sysadmin/data/registries/agents.json`)](#72-agent-registry-sysadmindataregistriesagentsjson)
  - [7.3 Rules Registry (`sysadmin/data/registries/rules.json`)](#73-rules-registry-sysadmindataregistriesrulesjson)
- [8. Dangers, Pitfalls & Mitigations](#8-dangers-pitfalls--mitigations)
- [9. Design Decisions & Open Explorations](#9-design-decisions--open-explorations)
  - [9.1 Resolved Architectural Decisions](#91-resolved-architectural-decisions)
  - [9.2 Remaining Open Explorations](#92-remaining-open-explorations)
- [10. Context Capture & Compression Strategy](#10-context-capture--compression-strategy)
  - [10.1 Why Full Context Matters](#101-why-full-context-matters)
  - [10.2 The Compression Problem](#102-the-compression-problem)
  - [10.3 Dual-Layer Storage Model](#103-dual-layer-storage-model)
  - [10.4 `ContextSnapshot` Schema](#104-contextsnapshot-schema)
  - [10.5 Storage Decision Table](#105-storage-decision-table)
  - [10.6 Storage Flow](#106-storage-flow)
  - [10.7 Projected Storage (dual-layer + tar.zst)](#107-projected-storage-dual-layer--tarzst)
  - [10.8 Updated `ExecutionResult` with Context Capture](#108-updated-executionresult-with-context-capture)
  - [10.9 Trajectory Record (Full Schema with Context Capture)](#109-trajectory-record-full-schema-with-context-capture)
  - [10.10 CoT SFT Reconstruction](#1010-cot-sft-reconstruction)
  - [10.11 Lossless Compression Layer (tar + zstd)](#1011-lossless-compression-layer-tar--zstd)
- [11. Relationship to Existing Architecture](#11-relationship-to-existing-architecture)

---

## 1. Foundational Alignment

This pipeline is built on top of the **Dual-Axis Taxonomy System** defined in the
sysadmin architecture. Every agent, message, and task in this pipeline operates within
these two axes:

### 1.1 Vertical Domain Taxonomy (task classification)

Tasks produced by the Architect MUST be tagged with at least one canonical domain from
`ollama_update/taxonomy.json`:

| Domain | Relevant Roles |
|:---|:---|
| Defensive Bash Scripting | Coder, Sysadmin |
| Binary Isolation | Coder, Sysadmin |
| ShellCheck | Coder, Reviewer |
| Ansible & Automation | Sysadmin, Orchestrator |
| Python Quality | Coder, Reviewer |
| Code Quality Toolchain | Reviewer, Coder |
| Docker & Containerization | Sysadmin, Security |
| Security & Hardening | Security, Reviewer |
| Multi-Agent Orchestration | Orchestrator, Architect |
| System Architecture | Architect, Orchestrator |

### 1.2 Horizontal Cognitive Taxonomy — The 6 Roles

The pipeline maps every agent to exactly one canonical role from the Horizontal
Cognitive Taxonomy:

| Role | Pipeline Agent | Primary Responsibility |
|:---|:---|:---|
| **Architect** | Architect | System design, task decomposition, tool selection |
| **Orchestrator** | Orchestrator | Task assignment, DAG construction, dispatch |
| **Reviewer** | Reviewer | Plan validation, rule enforcement, schema checks |
| **Security** | Security Gate *(new)* | Threat modeling, sandbox constraints, STRIDE review |
| **Coder** | Executor: `coder` | Code authorship, file writes, script generation |
| **Sysadmin** | Executor: `sysadmin` | Bash execution, systemd, Ansible, infrastructure ops |

> **Note on Security**: In the original discussion, Security was not a named pipeline
> stage. It is now promoted to a **first-class gate** between Reviewer and Dispatch
> to ensure STRIDE/hardening concerns are always addressed before execution.

> **Exclusivity of the 6 Roles**: The Horizontal Cognitive Taxonomy strictly comprises
> these 6 canonical roles. Ad-hoc roles (such as "researcher") are prohibited.
> Information gathering, web research, or documentation lookup are capabilities assigned
> to the **Architect** (for design research) or **Coder** (for technical documentation)
> via explicit tool access (`web_search`, `read_url`), not independent taxonomy roles.

### 1.3 Standard 4-Pillar Contract

Every agent's reasoning output MUST be structured around the 4-Pillar Contract.
This applies to both inter-agent messages (as structured JSON fields) and to any
LLM-generated prose emitted to the terminal-mcp stream:

| Pillar | Field name | Scope |
|:---|:---|:---|
| **Pillar 1: Analysis & Strategy** | `analysis` | Root-cause deconstruction; requirements analysis; cognitive decomposition |
| **Pillar 2: Risks & Edge Cases** | `risks` | Proactive threat modeling; anticipated failure modes; sandbox/permission constraints |
| **Pillar 3: Solution / Implementation** | `solution` | Tool calls, code, task assignments, or plan structure |
| **Pillar 4: Verification & Testing** | `verification` | Concrete assertions; idempotency checks; acceptance criteria |

All `rationale` fields in v1 schemas are **replaced** by the explicit 4-pillar
`cognition` block in v2. Free-form rationale is not permitted.

---

## 2. Updated Pipeline Flow

```
┌────────────────────────────────────────────────────────┐
│                    User Prompt (frozen)                │
└────────────────────────────┬───────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   ARCHITECT     │  Role: Architect
                    │  [Pillar 1–4]   │  ← Tool Registry + Rules Registry injected
                    └────────┬────────┘
                             │ PlanMessage (with 4-pillar cognition block)
                             ▼
                    ┌─────────────────┐
                    │  ORCHESTRATOR   │  Role: Orchestrator
                    │  [Pillar 1–4]   │  ← Agent Registry injected
                    └────────┬────────┘
                             │ AnnotatedPlanMessage (DAG + assignments + 4-pillar)
                             ▼
                    ┌─────────────────┐
                    │    REVIEWER     │  Role: Reviewer
                    │  [Pillar 1–4]   │  ← Tool Registry + Rules Registry injected
                    └────────┬────────┘
                        ┌────┴──────────────┐
          invalid tools │                   │ rule/schema violation
                        ▼                   ▼
                   ARCHITECT          ORCHESTRATOR     ← typed feedback with violations
                        │                   │
                        └─────────┬─────────┘
                         approved │
                                  ▼
                    ┌─────────────────┐
                    │  SECURITY GATE  │  Role: Security   ← NEW in v2
                    │  [Pillar 2 ★]   │  ← STRIDE rules + sandbox constraints injected
                    └────────┬────────┘
                        ┌────┴─────┐
          threat found  │          │ cleared
                        ▼          ▼
                   ARCHITECT   ORCHESTRATOR (dispatch)
                                   │ TaskMessage (per task, with 4-pillar context)
                                   ▼
                         ┌──────────────────┐
                         │   EXECUTOR(S)    │
                         │  coder/sysadmin  │  Roles: Coder | Sysadmin
                         │  [Pillar 1–4]    │
                         └────────┬─────────┘
                                  │ ExecutionResult (with 4-pillar trace)
                                  ▼
                    ┌─────────────────────────┐
                    │  ORCHESTRATOR           │  collects, gates, re-plans
                    │  Continuous Learning    │  → MemoryStore lesson extraction
                    └─────────────────────────┘
```

---

## 3. Message Schemas (v2 — 4-Pillar Aligned)

All inter-agent messages carry a `cognition` block containing all four pillars.
This is the primary mechanism by which reasoning traces are preserved across handoffs
and eventually fed into the trajectory/learning pipeline.

### 3.1 `Cognition` Block (embedded in every message)

```json
{
  "cognition": {
    "analysis": "<Pillar 1: Root-cause deconstruction, requirements analysis>",
    "risks": "<Pillar 2: Anticipated failure modes, constraints, threat modeling>",
    "solution": "<Pillar 3: Summary of this agent's decision — assignments, tool choices, etc.>",
    "verification": "<Pillar 4: How this output will be validated — acceptance criteria>"
  }
}
```

### 3.2 `PlanMessage` (Architect → Orchestrator)

```json
{
  "schema_version": "2.0",
  "message_type": "plan",
  "run_id": "<uuid4>",
  "revision": 0,
  "revision_diff": "<summary of changes from prior revision, or null if first>",
  "original_prompt": "<verbatim user prompt — NEVER modified>",
  "goal_summary": "<one-sentence summary>",
  "tasks": [
    {
      "task_id": "t-001",
      "description": "<what this task does>",
      "domain_tags": ["<taxonomy domain from taxonomy.json>"],
      "agent_hint": "<suggested role: coder|sysadmin>",
      "tools_required": ["<tool_name>"],
      "inputs": ["<task_id of dependency>"],
      "outputs": ["<named artifact or result>"],
      "constraints": ["<rule or constraint this task must satisfy>"]
    }
  ],
  "open_questions": ["<anything uncertain>"],
  "cognition": {
    "analysis": "...",
    "risks": "...",
    "solution": "...",
    "verification": "..."
  }
}
```

### 3.3 `AnnotatedPlanMessage` (Orchestrator → Reviewer)

```json
{
  "schema_version": "2.0",
  "message_type": "annotated_plan",
  "run_id": "<uuid4>",
  "revision": 0,
  "original_prompt": "<verbatim — copied unchanged>",
  "goal_summary": "<copied from PlanMessage>",
  "dag": {
    "nodes": ["t-001", "t-002"],
    "edges": [{"from": "t-001", "to": "t-002", "type": "data_dependency"}]
  },
  "tasks": [
    {
      "task_id": "t-001",
      "description": "<copied>",
      "domain_tags": ["<copied from PlanMessage>"],
      "assigned_agent": "<role: coder|sysadmin>",
      "assigned_model": "<model_preference from Agent Registry>",
      "tools_required": ["<tool_name>"],
      "inputs": [],
      "outputs": ["artifact-A"],
      "constraints": [],
      "execution_order": 1,
      "parallel_group": null
    }
  ],
  "cognition": {
    "analysis": "...",
    "risks": "...",
    "solution": "...",
    "verification": "..."
  }
}
```

### 3.4 `ReviewVerdict` (Reviewer → next agent)

```json
{
  "schema_version": "2.0",
  "message_type": "review_verdict",
  "run_id": "<uuid4>",
  "revision": 0,
  "verdict": "approved | rejected_tools | rejected_rules",
  "return_to": "architect | orchestrator | null",
  "violations": [
    {
      "violation_id": "v-001",
      "type": "invalid_tool | unknown_agent | rule_violation | dag_error | schema_error | domain_tag_missing",
      "task_id": "<task_id or null>",
      "rule_ref": "<rule ID from Rules Registry or null>",
      "tool_ref": "<tool name from Tool Registry or null>",
      "domain_ref": "<taxonomy domain or null>",
      "pillar_ref": "<1|2|3|4 — which pillar this violation is in>",
      "description": "<precise violation description>",
      "severity": "blocking | warning"
    }
  ],
  "cognition": {
    "analysis": "<what the reviewer found>",
    "risks": "<risks if this plan were executed as-is>",
    "solution": "<what must change — without prescribing the fix>",
    "verification": "<what a passing plan must satisfy>"
  }
}
```

### 3.5 `SecurityVerdict` (Security Gate → Orchestrator or Architect)

```json
{
  "schema_version": "2.0",
  "message_type": "security_verdict",
  "run_id": "<uuid4>",
  "verdict": "cleared | rejected_security",
  "fault_type": "scope | assignment | sandbox | null",
  "return_to": "architect | orchestrator | null",
  "threats": [
    {
      "threat_id": "th-001",
      "stride_category": "Spoofing | Tampering | Repudiation | Information Disclosure | DoS | Elevation of Privilege",
      "task_id": "<task_id>",
      "description": "<threat description>",
      "severity": "critical | high | medium | low",
      "mitigation_required": true
    }
  ],
  "cognition": {
    "analysis": "<STRIDE analysis of the plan>",
    "risks": "<ranked threat surface>",
    "solution": "<required mitigations before execution>",
    "verification": "<how to confirm mitigations are in place>"
  }
}
```

> **Deterministic Security Routing via `fault_type`**:
> - `scope`: The threat stems from task decomposition, forbidden intent, or architectural hazard → `return_to: "architect"` (Architect budget -1).
> - `assignment`: The threat stems from over-permissioned tools, improper role assignment, or missing dry-run dependency → `return_to: "orchestrator"` (Orchestrator budget -1).
> - `sandbox`: The threat stems from isolation/container boundaries → `return_to: "orchestrator"` to adjust environment constraints.

### 3.6 `TaskMessage` (Orchestrator → Executor)

```json
{
  "schema_version": "2.0",
  "message_type": "task",
  "run_id": "<uuid4>",
  "task_id": "t-001",
  "role": "coder | sysadmin",
  "description": "<task description>",
  "domain_tags": ["<taxonomy domain>"],
  "tools_available": [
    {"name": "<tool>", "schema": {}}
  ],
  "inputs": {
    "<artifact_name>": "<value or file reference>"
  },
  "constraints": ["<rule or constraint>"],
  "injected_lessons": ["<lesson text from MemoryStore FTS5 retrieval>"],
  "original_prompt": "<verbatim — always available as ground truth>",
  "expected_cognition": {
    "analysis": "required",
    "risks": "required",
    "solution": "required",
    "verification": "required"
  }
}
```

> The `expected_cognition` field explicitly signals to the executor model that all four
> pillar sections are required outputs. This primes the model's `Analysis & Strategy`
> phase and enables trajectory capture of the full cognitive trace.

### 3.7 `ExecutionResult` (Executor → Orchestrator)

```json
{
  "schema_version": "2.0",
  "message_type": "execution_result",
  "run_id": "<uuid4>",
  "task_id": "t-001",
  "role": "coder | sysadmin",
  "status": "success | failure | partial",
  "outputs": {
    "<artifact_name>": "<value or file reference>"
  },
  "error": {
    "code": "<error type>",
    "message": "<error description>",
    "recoverable": true
  },
  "cognition": {
    "analysis": "<what the executor found / understood>",
    "risks": "<risks it anticipated or encountered>",
    "solution": "<what it did>",
    "verification": "<what it checked to confirm correctness>"
  },
  "telemetry": {
    "duration_ms": 0,
    "tool_calls_made": [],
    "tokens_per_second": 0,
    "context_tokens": 0,
    "model_used": "<model name>"
  }
}
```

---

## 4. Agent Contracts (6-Role Aligned)

### 4.1 Architect *(Role: Architect)*

| Property | Value |
|:---|:---|
| **Input** | User prompt (frozen) + Tool Registry + Rules Registry + injected MemoryStore lessons |
| **Output** | `PlanMessage` with 4-pillar `cognition` block |
| **Authority** | Design tasks; suggest tools from Tool Registry; suggest executor roles; tag domains |
| **MUST NOT** | Invent tools not in Tool Registry; modify original prompt; assign models (Orchestrator's job) |
| **Revision trigger** | `ReviewVerdict.verdict == "rejected_tools"` OR `SecurityVerdict.verdict == "rejected_security"` |
| **Revision budget** | Max **3 revisions** per run |
| **Pillar focus** | Pillar 1 (decomposition) and Pillar 3 (task structure) are primary outputs |
| **Exit on budget exhaustion** | Escalate to human; emit `run_aborted(reason="architect_budget_exhausted")` |

**Anti-loop guard**: Revised `PlanMessage.revision_diff` must be non-empty. If identical
plan (by canonical JSON hash) is re-submitted, pipeline aborts immediately.

---

### 4.2 Orchestrator *(Role: Orchestrator)*

| Property | Value |
|:---|:---|
| **Input** | `PlanMessage` + Agent Registry + `ReviewVerdict` (on revision) |
| **Output** | `AnnotatedPlanMessage` (pre-dispatch) and `TaskMessage` per task (dispatch) |
| **Authority** | Assign roles and models; build execution DAG; determine parallelization; collect `ExecutionResult`; re-plan sub-tasks on recoverable failure |
| **MUST NOT** | Modify task descriptions or constraints; invent tasks not in the approved plan without Reviewer re-approval |
| **Revision trigger** | `ReviewVerdict.verdict == "rejected_rules"` |
| **Revision budget** | Max **3 revisions** per run |
| **Pillar focus** | Pillar 3 (assignment decisions) and Pillar 4 (DAG correctness assertions) |
| **Exit on budget exhaustion** | Escalate to human; emit `run_aborted(reason="orchestrator_budget_exhausted")` |

**Scope boundary**: If fixing a `rejected_rules` verdict requires changing task
*scope* (not just assignment), Orchestrator MUST escalate to Architect (decrement
Architect budget) rather than silently expanding or collapsing tasks.

---

### 4.3 Reviewer *(Role: Reviewer)*

| Property | Value |
|:---|:---|
| **Input** | `AnnotatedPlanMessage` + Tool Registry + Rules Registry + original prompt |
| **Output** | `ReviewVerdict` with 4-pillar `cognition` block |
| **Authority** | Pass/reject plan; classify violations by type/severity; cite specific rule and tool refs |
| **MUST NOT** | Suggest fixes (only flag violations); modify plan; approve with any `blocking` violations present |

**Validation checklist** — executed in order:

| Step | Check | Method |
|:---|:---|:---|
| 1 | Schema conformance (`AnnotatedPlanMessage` v2.0) | Deterministic (JSON Schema) |
| 2 | Tool validity — every `tools_required` in Tool Registry | Deterministic (registry lookup) |
| 3 | Agent/role validity — every `assigned_agent` in Agent Registry | Deterministic (registry lookup) |
| 4 | Domain tag validity — every `domain_tag` in `taxonomy.json` | Deterministic (registry lookup) |
| 5 | DAG validity — no cycles; all `inputs` reference prior outputs | Deterministic (graph traversal) |
| 6 | Rule validation — constraints do not violate Rules Registry entries | LLM-assisted (rules injected as JSON) |
| 7 | Prompt fidelity — `original_prompt` byte-identical to frozen original | Deterministic (hash comparison) |
| 8 | Scope creep — no task exceeds original prompt scope | LLM-assisted (pillar 1: analysis) |
| 9 | 4-Pillar completeness & substance — all 4 fields present, >= 30 chars, no placeholder evasions | Deterministic (schema & substance check) |

> [!IMPORTANT]
> **Deterministic Pre-Filter (`sysadmin/validator.py`)**: Steps 1–5, 7, and 9 are executed
> programmatically by a fast Python validator *before* calling the LLM Reviewer.
> If any deterministic check fails, a `ReviewVerdict` is generated immediately with typed
> violations, returning early and saving LLM compute. Only plans that pass all deterministic
> checks proceed to LLM-assisted evaluation (Steps 6 and 8).
> The Reviewer MUST cite `pillar_ref` in each violation to enable targeted rework.

---

### 4.4 Security Gate *(Role: Security)*

| Property | Value |
|:---|:---|
| **Input** | `AnnotatedPlanMessage` (post Reviewer approval) + STRIDE rules + sandbox constraint registry |
| **Output** | `SecurityVerdict` with 4-pillar `cognition` block |
| **Authority** | Perform STRIDE threat modeling; require mitigations; block execution on critical threats |
| **MUST NOT** | Modify plan; approve if any `critical` or `high` unmitigated threats present |
| **Revision trigger** | N/A — on `rejected_security`, returns to Architect (critical scope issues) or Orchestrator (assignment/constraint fixes) |
| **Pillar focus** | **Pillar 2 is primary** — Risks & Edge Cases is this role's entire domain |

Security Gate checks:

1. STRIDE threat modeling per task (especially tasks using destructive tools or elevated permissions)
2. Dry-run prerequisite enforcement (Rule R-001: any destructive task must have a dry-run dependency)
3. Sandbox constraint validation (seccomp, socket isolation, Bubblewrap namespace checks)
4. Secret exposure check (Rule R-002: no tokens/passwords in task descriptions or constraints)
5. Privilege escalation surface review (executor role vs. required tool permissions)

---

### 4.5 Executor: Coder *(Role: Coder)*

| Property | Value |
|:---|:---|
| **Input** | `TaskMessage` (role: coder) |
| **Output** | `ExecutionResult` with 4-pillar `cognition` block |
| **Preferred model** | `qwen2.5-coder:7b` |
| **Allowed tools** | `read_file`, `write_file`, `run_bash` (lint/test only, no system modification) |
| **MUST NOT** | Expand task scope; use tools not in `TaskMessage.tools_available`; emit success without assertion |
| **Pillar focus** | Pillar 3 (code authorship) and Pillar 4 (ShellCheck / pytest verification) |
| **Linter gate** | All bash outputs pass ShellCheck; all Python outputs pass pytest before `status: success` |

---

### 4.6 Executor: Sysadmin *(Role: Sysadmin)*

| Property | Value |
|:---|:---|
| **Input** | `TaskMessage` (role: sysadmin) |
| **Output** | `ExecutionResult` with 4-pillar `cognition` block |
| **Preferred model** | `qwen3:8b` |
| **Allowed tools** | `run_bash`, `read_file`, `write_file`, `service_status`, `journal_logs`, `ansible_syntax_check` |
| **MUST NOT** | Run destructive commands without a confirmed dry-run task output in `TaskMessage.inputs`; assume system state |
| **Pillar focus** | Pillar 1 (system state analysis) and Pillar 2 (risk enumeration before any write/exec) |
| **Bash standard** | All scripts MUST follow `AGENTS.md` bash standard: `set -euo pipefail`, ERR trap, explicit binary paths |

---

### 4.7 Single-Model Multi-Persona (SMMP) Execution Profile

To optimize execution on consumer and local GPU workstations (8GB–24GB VRAM), the pipeline defines
the **Single-Model Multi-Persona (SMMP)** execution mode. Rather than incurring heavy VRAM model-swapping
penalties (2–10s latency per pipeline stage, causing 20–60s+ of PCIe/RAM thrashing per run), the pipeline
pins a single capable foundation model (default: `qwen2.5-coder:7b` or `qwen3:8b`) in VRAM (`keep_alive: -1`)
and dynamically shifts cognitive roles with **0 ms model-loading latency**.

```
                ┌────────────────────────────────────────────────────────┐
                │        Resident Foundation Model (VRAM-Pinned)         │
                │        e.g., qwen2.5-coder:7b (keep_alive: -1)         │
                └───────────────────────────┬────────────────────────────┘
                                            │
         ┌──────────────────────────────────┼──────────────────────────────────┐
         ▼                                  ▼                                  ▼
   [ ARCHITECT ]                      [ REVIEWER ]                      [ SECURITY ]
   • Fresh Context (stateless)        • Fresh Context (stateless)        • Fresh Context (stateless)
   • Prompt: roles/architect.md       • Prompt: roles/reviewer.md        • Prompt: roles/security.md
   • Temp: 0.25 (decomposition)       • Temp: 0.0 (adversarial audit)    • Temp: 0.0 (STRIDE modeling)
   • Tools: read_file, web_search     • Tools: None (pure audit)         • Tools: Sandbox registry
   • Schema: PlanMessage              • Schema: ReviewVerdict            • Schema: SecurityVerdict
```

#### The Four Runtime Dials

For each stage in the pipeline, the runner resets and modulates four distinct parameters:

| Dial | Mechanism | Purpose |
|:---|:---|:---|
| **1. Stateless Context Reset** | Drop conversation history; inject clean `[system, user]` message pair | Prevents context drift, token bloat, and hallucination contamination across role transitions |
| **2. Role Persona Conditioning** | Inject dedicated system prompt from `sysadmin/prompts/roles/{role}.md` | Establishes role identity, cognitive focus, authority boundaries, and expected output schema |
| **3. Sampling Profile Tuning** | Set dynamic Ollama `options` (`temperature`, `top_p`) per role | Tunes cognitive posture: exploratory for Architect, greedy/deterministic for Reviewer/Security |
| **4. Tool Registry Masking** | Pass role-filtered `tools` list in Ollama API call | Guarantees physical tool confinement (e.g. Coder cannot call `service_status`; Reviewer has no execution tools) |

#### Role Sampling Profiles

```python
SMMP_PROFILES = {
    "architect":    {"temperature": 0.25, "top_p": 0.90, "description": "Creative decomposition & alternatives"},
    "orchestrator": {"temperature": 0.10, "top_p": 0.80, "description": "Deterministic DAG construction & scheduling"},
    "reviewer":     {"temperature": 0.00, "top_p": 1.00, "description": "Greedy decoding for strict, reproducible auditing"},
    "security":     {"temperature": 0.00, "top_p": 1.00, "description": "Greedy decoding for adversarial STRIDE threat modeling"},
    "coder":        {"temperature": 0.05, "top_p": 0.85, "description": "High-precision code syntax & ShellCheck compliance"},
    "sysadmin":     {"temperature": 0.00, "top_p": 1.00, "description": "Zero-hallucination bash & systemd command generation"},
}
```

#### Mitigating "Self-Review Bias" Under SMMP

When a single foundation model audits its own proposed plans, it risks self-confirmation bias.
The architecture enforces three structural counter-measures:
1. **Deterministic Pre-Filter (`sysadmin/validator.py`)**: Reviewer checks 1–5, 7, and 9 run in pure Python before the LLM is queried. Schema violations, unknown tools, DAG cycles, and R-006 length deficits are rejected programmatically.
2. **Adversarial Negative Framing**: The Reviewer and Security Gate system prompts explicitly instruct the model to assume the plan author was negligent, framing the task as finding reasons to reject or harden.
3. **Blind Context Handoff**: The Reviewer never sees the Architect's internal reasoning or draft attempts—only the frozen, formal JSON contract (`AnnotatedPlanMessage`).

---

## 5. Loop Conditions & Exit Rules

### 5.1 Feedback Loop Matrix

| Verdict | Source | `fault_type` | Return To | What Changes | Budget |
|:---|:---|:---|:---|:---|:---|
| `rejected_tools` | Reviewer | — | Architect | Tool selection redesign | Architect -1 |
| `rejected_rules` | Reviewer | — | Orchestrator | Assignment / DAG adjustment | Orchestrator -1 |
| `rejected_security` | Security Gate | `scope` | Architect | Task scope / constraint redesign | Architect -1 |
| `rejected_security` | Security Gate | `assignment` / `sandbox` | Orchestrator | Permission / tool constraint adjustment | Orchestrator -1 |
| `approved` | Reviewer | — | Security Gate | — | — |
| `cleared` | Security Gate | — | Orchestrator (dispatch) | — | — |

### 5.2 Budget Exhaustion & Human Escalation Checkpoints

```
IF architect_revisions_remaining == 0:
    checkpoint = save_checkpoint(status="aborted", reason="architect_budget_exhausted", last_verdict=...)
    emit run_aborted(checkpoint_path=checkpoint)
    escalate_to_human(checkpoint)
    STOP

IF orchestrator_revisions_remaining == 0:
    checkpoint = save_checkpoint(status="aborted", reason="orchestrator_budget_exhausted", last_verdict=...)
    emit run_aborted(checkpoint_path=checkpoint)
    escalate_to_human(checkpoint)
    STOP
```

**Resumable Checkpoints**: `escalate_to_human()` writes a structured `run_aborted.json`
checkpoint to `sysadmin/data/runs/<run_id>/state.json`. The CLI reports the failure reason,
offending task/verdict diff, and instructions. The operator can inspect or adjust the plan
and resume execution via:
```bash
python sysadmin/pipeline.py --resume <run_id>
```

### 5.3 Identical Plan Detection (Anti-Loop Guard)

```python
canonical = json.dumps(plan["tasks"], sort_keys=True, separators=(',', ':'))
if sha256(canonical) == sha256(prior_canonical):
    emit run_aborted(reason="no_progress_detected")
    escalate_to_human()
    STOP
```

### 5.4 Executor Failure Handling (Inner Loop & Recovery Governance)

```
ExecutionResult.status == "failure":
    IF recoverable AND retries < 2:
        # Same task retry: inject failure cognition directly into task prompt
        Orchestrator re-issues TaskMessage with executor's cognition.risks appended
        to injected_lessons (isolated to this task; not yet global MemoryStore)
    ELSE IF Orchestrator attempts fallback task synthesis:
        # NEW recovery task governance:
        IF fallback task requires new tools or alters execution commands:
            Route fallback task through expedited Reviewer + Security Gate validation
            before dispatch.
        ELSE:
            Dispatch fallback task directly.
    ELSE (unrecoverable OR retries exhausted):
        Mark task failed; DAG traversal to identify downstream impact
        IF critical path blocked → escalate_to_human()
        ELSE → continue non-dependent tasks; emit partial run summary
        → Extract negative lesson from cognition.risks to MemoryStore (upon run completion)
```

---

## 6. State & Persistence

### 6.1 Run State (external, by `run_id`)

`sysadmin/data/runs/<run_id>/state.json`:

```json
{
  "run_id": "<uuid4>",
  "status": "running | approved | security_cleared | aborted | complete | partial",
  "original_prompt": "<verbatim>",
  "architect_revisions_used": 0,
  "orchestrator_revisions_used": 0,
  "current_phase": "architect | orchestrator | reviewer | security | dispatch | collecting",
  "messages": {
    "plan": "<path>",
    "annotated_plan": "<path>",
    "review_verdict": "<path>",
    "security_verdict": "<path>"
  },
  "tasks": {
    "t-001": {"status": "pending | running | success | failure", "retries": 0, "role": "coder"}
  },
  "events": [
    {"ts": "<ISO-8601>", "event": "<event_type>", "pillar": "<1|2|3|4>", "detail": "<string>"}
  ]
}
```

Events are tagged with `pillar` to enable post-run learning analysis by pillar weakness.

### 6.2 Continuous Learning Hooks & Lesson Timing Policy

**Timing & Anti-Contamination Rules**:
- **Intra-run task retries**: When a task fails with `status == "failure"`, its `cognition.risks`
  is injected *only* into immediate retries of that exact task (`retries < 2`). It is NOT
  injected into other tasks within the same run to prevent circular error propagation.
- **Inter-run MemoryStore injection**: Extraction into global `MemoryStore` (via `extraction.py`)
  occurs strictly at run completion (`status == "complete"` or `status == "aborted"`). Only lessons
  from sealed runs become eligible for FTS5 retrieval in subsequent pipeline runs.

On every `run_aborted` or `ExecutionResult.status == "failure"`:
- Extract `cognition.risks` → **negative lesson** → MemoryStore (`extraction.py`)

On every `ExecutionResult.status == "success"` with `iterations == 1`:
- Extract `cognition.risks` (pre-emptive mitigations) → **positive lesson** → MemoryStore

On run `complete` or `partial`:
- Write trajectory to `sysadmin/data/trajectories.jsonl` (full 4-pillar cognition block preserved)
- Feed into CoT SFT/DPO dataset pipeline via `dataset.py`

---

## 7. Registries

### 7.1 Tool Registry (`sysadmin/data/registries/tools.json`)

```json
{
  "version": "2.0",
  "tools": [
    {
      "name": "run_bash",
      "description": "Execute a bash command",
      "parameters": {"command": "string"},
      "safe_for_dry_run": false,
      "requires_approval": true,
      "allowed_roles": ["coder", "sysadmin"],
      "domain_tags": ["Defensive Bash Scripting", "Binary Isolation"]
    }
  ]
}
```

### 7.2 Agent Registry (`sysadmin/data/registries/agents.json`)

```json
{
  "version": "2.0",
  "execution_mode": "SMMP",
  "default_foundation_model": "qwen2.5-coder:7b",
  "agents": [
    {
      "type": "coder",
      "taxonomy_role": "Coder",
      "description": "Writes and edits code files; runs linters",
      "allowed_tools": ["read_file", "write_file", "run_bash"],
      "model_preference": "qwen2.5-coder:7b",
      "domain_affinity": ["Defensive Bash Scripting", "Python Quality", "ShellCheck", "Code Quality Toolchain"]
    },
    {
      "type": "sysadmin",
      "taxonomy_role": "Sysadmin",
      "description": "Linux/Ansible system administration and infrastructure ops",
      "allowed_tools": ["run_bash", "read_file", "write_file", "service_status", "journal_logs", "ansible_syntax_check"],
      "model_preference": "qwen2.5-coder:7b",
      "domain_affinity": ["Ansible & Automation", "Docker & Containerization", "Security & Hardening"]
    }
  ]
}
```

### 7.3 Rules Registry (`sysadmin/data/registries/rules.json`)

```json
{
  "version": "2.0",
  "rules": [
    {
      "id": "R-001",
      "name": "no_destructive_without_dry_run",
      "pillar": 2,
      "domain": "Security & Hardening",
      "description": "Any task using a destructive tool must have a dry-run task as a prerequisite in the DAG",
      "check": "if task.tools_required contains destructive_tool then task.inputs must contain dry_run_task_output"
    },
    {
      "id": "R-002",
      "name": "no_secrets_in_plan",
      "pillar": 2,
      "domain": "Security & Hardening",
      "description": "Task descriptions and constraints must not contain secret values",
      "check": "regex scan for token/password/key patterns"
    },
    {
      "id": "R-003",
      "name": "bash_standard_compliance",
      "pillar": 3,
      "domain": "Defensive Bash Scripting",
      "description": "All bash tasks must declare set -euo pipefail, ERR trap, and explicit binary paths",
      "check": "coder executor linter gate (ShellCheck + pattern check)"
    },
    {
      "id": "R-004",
      "name": "binary_isolation_required",
      "pillar": 3,
      "domain": "Binary Isolation",
      "description": "Executor tasks must not rely on ambient $PATH; resolve venv/binary paths deterministically",
      "check": "no bare tool invocations without explicit path resolution in task constraints"
    },
    {
      "id": "R-005",
      "name": "domain_tag_required",
      "pillar": 1,
      "domain": "System Architecture",
      "description": "Every task must carry at least one canonical domain_tag from taxonomy.json",
      "check": "deterministic lookup against taxonomy.json aliases + canonicals"
    },
    {
      "id": "R-006",
      "name": "four_pillar_cognition_required",
      "pillar": null,
      "domain": "Multi-Agent Orchestration",
      "description": "Every agent message must include a substantive cognition block with all four pillars (analysis, risks, solution, verification)",
      "check": "all 4 fields present AND length >= 30 chars each AND disallow placeholder evasion ('none', 'n/a', 'ok', 'null', 'not applicable')"
    }
  ]
}
```

---

## 8. Dangers, Pitfalls & Mitigations

| # | Danger | Pillar | Mitigation |
|:---|:---|:---|:---|
| 1 | **Infinite feedback loops** | 3 | Revision budgets (§5.2); identical-plan hash guard (§5.3) |
| 2 | **Plan drift / context corruption** | 1 | Frozen `original_prompt`; Reviewer step 7 (prompt fidelity hash) |
| 3 | **Reviewer hallucinating tool validity** | 2 | Tool Registry injected as JSON; steps 1–5 are deterministic |
| 4 | **Orchestrator over-parallelizing** | 4 | DAG with explicit `depends_on`; Reviewer step 5 (DAG validation) |
| 5 | **Rule scope ambiguity** | 2 | Machine-readable Rules Registry; violations cite `rule_ref` + `pillar_ref` |
| 6 | **Responsibility diffusion** | 1 | Explicit 6-role ownership contracts; Executor still fail-safes |
| 7 | **Token budget explosion** | 3 | External run state; agents receive slices by run_id |
| 8 | **Executor feedback ignored** | 4 | `ExecutionResult.cognition` + Orchestrator inner loop with immediate lesson injection |
| 9 | **Security concerns missed** | 2 | Security Gate is a mandatory, named pipeline stage (not a Reviewer checkbox) |
| 10 | **4-pillar sections empty or superficial** | all | R-006 enforces non-empty cognition with length threshold (>=30 chars) and anti-placeholder check; Reviewer step 9 blocks |
| 11 | **Domain tag drift (lesson sprawl)** | 1 | Reviewer step 4 validates domain tags against `taxonomy.json`; aliases enforced |
| 12 | **Unvetted recovery tasks** | 4 | §5.4 enforces expedited Reviewer + Security Gate pass for any new fallback tasks |
| 13 | **Circular intra-run lesson contamination** | 1 | §6.2 scopes failure cognition strictly to task retries; global MemoryStore extraction delayed to run seal |

---

## 9. Design Decisions & Open Explorations

### 9.1 Resolved Architectural Decisions

1. **Taxonomy Purity & Role Exclusivity**:
   The Horizontal Cognitive Taxonomy strictly comprises the 6 canonical roles (Architect, Coder, Orchestrator, Reviewer, Security, Sysadmin). Ad-hoc roles like "researcher" are removed. Research capabilities (`web_search`, `read_url`) are assigned as tools to the **Architect** (for system design discovery) or **Coder** (for technical documentation lookup).

2. **Deterministic Pre-Filter Optimization**:
   Reviewer steps 1–5, 7, and 9 are executed programmatically via `sysadmin/validator.py` before invoking LLM Reviewer. If any deterministic check fails, a typed `ReviewVerdict` is returned immediately, conserving local LLM inference compute.

3. **Substantive Cognition Enforcement (R-006)**:
   Cognition fields cannot be bypassed with trivial strings (`"none"`, `"ok"`). Rule R-006 enforces all 4 pillars with a >= 30 character threshold and anti-placeholder verification.

4. **Deterministic Security Routing**:
   `SecurityVerdict` includes a `fault_type` field (`"scope"` vs `"assignment"` / `"sandbox"`). Scope threats route back to the Architect; assignment and sandbox constraint threats route back to the Orchestrator.

5. **Recovery Task Governance**:
   On executor failure, Orchestrator may only re-try the same task directly. Any newly synthesized fallback task that alters tools or execution commands must pass expedited Reviewer + Security Gate checks before dispatch.

6. **Lesson Timing & Anti-Contamination**:
   Intra-run lesson feedback is strictly localized to immediate task retries (`retries < 2`). Global extraction to `MemoryStore` occurs strictly upon run completion (`complete` or `aborted`) to prevent circular lesson contamination within the active DAG.

7. **Human Escalation via Resumable Checkpoints**:
   `escalate_to_human()` writes a structured `run_aborted.json` checkpoint event and alerts the operator. The pipeline can be resumed via `python sysadmin/pipeline.py --resume <run_id>`.

8. **Single-Model Multi-Persona (SMMP) Execution Baseline**:
   Default to a single VRAM-pinned foundation model (`keep_alive: -1`) executing all 6 roles via stateless context resets, dynamic system prompt injection, role-specific sampling profiles, and tool masking (§4.7). Eliminates PCIe model swapping latency entirely.

### 9.2 Remaining Open Explorations

1. **Security Gate Model Specialization (Tier 2 Multi-Model Evaluation)**:
   Under SMMP, Security Gate runs on the shared foundation model using temperature 0.0 and adversarial prompt conditioning. As an open exploration for workstations with >= 24GB VRAM, evaluate whether running a concurrently resident, dedicated auditor model (e.g. `Modelfile-security-codestral`) provides significantly higher threat detection yield than SMMP adversarial prompting.

2. **Executor Isolation Tier**: Sandboxed process (Bubblewrap namespaces) vs. rootless container (Docker/Podman) — affects `safe_for_dry_run` and Sysadmin's ability to inspect host `service_status` and `journal_logs`.

3. **Partial Success Deliverable Policy**: Who (Orchestrator or human operator) decides whether a partial run (where non-critical tasks succeeded but an optional leaf task failed) constitutes an acceptable deliverable?

---

## 10. Context Capture & Compression Strategy

Capturing the full context window alongside each execution result is essential for
high-fidelity training data and reproducible lesson extraction. However, naive
full-context storage creates prohibitive overhead. This section defines a
**dual-layer strategy**: content-addressed references where data is reusable, and
verbatim storage where training signal lives — then lossless tar.zst compression
over everything at rest.

### 10.1 Why Full Context Matters

A model's output is a function of its *entire* input window — not just the user
prompt. Without capturing what was injected, you cannot:

- Reproduce the exact conditions that caused a pass or failure
- Construct valid DPO pairs (same context, different outputs)
- Train FTS5 retrieval to surface lessons in the right contexts
- Detect when behavior changes because context changed (new rule) vs. model improved

### 10.2 The Compression Problem

Estimated per-task context sizes:

| Component | Size | Training Critical? |
|:---|:---|:---|
| System/role prompt | ~2 KB | No |
| Injected MemoryStore lessons | ~3–8 KB | Reference only (lesson IDs sufficient) |
| Tool Registry snapshot | ~5–15 KB | No (version tag sufficient) |
| Rules Registry snapshot | ~2–5 KB | No (version tag sufficient) |
| Agent Registry snapshot | ~1–3 KB | No (version tag sufficient) |
| TaskMessage (full) | ~3–10 KB | Stored as file ref |
| `cognition` block (all 4 pillars) | ~4–8 KB | **YES — verbatim required** |
| Code / script output | ~2–10 KB | **YES — verbatim required** |

For a 10-task run: **~220–590 KB** naively inline. At 1,000 runs: **~220–590 MB**.

### 10.3 Dual-Layer Storage Model

```
  Run execution completes
          │
          ├──► LAYER 1: ContextSnapshot (stored by reference)
          │    • Registry version tags (not full content)
          │    • Injected lesson IDs (not lesson text)
          │    • TaskMessage file ref (not inline)
          │    • System prompt hash
          │    → Written to: runs/<run_id>/tasks/<task_id>/context_snapshot.json
          │
          └──► LAYER 2: TrajectoryRecord (stored verbatim)
               • cognition.analysis    ← NEVER compressed
               • cognition.risks       ← NEVER compressed
               • cognition.solution    ← NEVER compressed
               • cognition.verification← NEVER compressed
               • code / script output  ← NEVER compressed
               → Written to: data/trajectories.jsonl
```

> [!IMPORTANT]
> The `cognition` block pillars are **training gold** and must always be stored
> verbatim. Any lossy transformation of Pillars 1–2 (Analysis + Risks) destroys
> the causal chain that CoT SFT trains models to reproduce: a model learns
> *what* to do but not *why*, eliminating the value of Chain-of-Thought fine-tuning.

### 10.4 `ContextSnapshot` Schema

Stored at `sysadmin/data/runs/<run_id>/tasks/<task_id>/context_snapshot.json`:

```json
{
  "schema_version": "1.0",
  "run_id": "<uuid4>",
  "task_id": "t-001",
  "role": "coder | sysadmin",
  "captured_at": "<ISO-8601 UTC>",
  "system_prompt_hash": "<sha256 of exact system/role prompt text>",
  "tool_registry_version": "2.0",
  "rules_registry_version": "2.0",
  "agent_registry_version": "2.0",
  "injected_lesson_ids": ["lesson-001", "lesson-003"],
  "injected_lesson_count": 2,
  "task_message_ref": "runs/<run_id>/tasks/t-001/task_message.json",
  "context_token_estimate": 1240,
  "model_used": "qwen2.5-coder:7b"
}
```

Full reproducibility: `system_prompt_hash` + registry versions + `task_message_ref`
+ `injected_lesson_ids` → can reconstruct the exact input window from versioned files.

### 10.5 Storage Decision Table

| Data | Store how? | Rationale |
|:---|:---|:---|
| `cognition.analysis` | **Verbatim inline** | Pillar 1 — CoT SFT training signal |
| `cognition.risks` | **Verbatim inline** | Pillar 2 — DPO rejected-trace signal |
| `cognition.solution` | **Verbatim inline** | Pillar 3 — implementation trace |
| `cognition.verification` | **Verbatim inline** | Pillar 4 — assertion trace |
| Code / script outputs | **Verbatim inline** | Exact output required for diff and training |
| System/role prompt | SHA-256 hash ref | Static per role; deduplicated across runs |
| Tool Registry | Version tag ref | Changes rarely; stored once per version |
| Rules Registry | Version tag ref | Changes rarely; stored once per version |
| Agent Registry | Version tag ref | Changes rarely; stored once per version |
| Injected lesson text | Lesson ID list | Full text reconstructed from MemoryStore |
| TaskMessage (full) | File ref | Stored as `task_message.json` in run dir |
| Coordination prose | Verbatim inline | Small; no semantic compression applied |

### 10.6 Storage Flow

```
  Run execution completes
          │
          ├──► LAYER 1: ContextSnapshot (stored by reference)
          │    • SHA-256 hash of system/role prompt
          │    • Registry version tags (tools, rules, agents)
          │    • Injected lesson IDs (not lesson text)
          │    • File ref to task_message.json
          │    → Written to: runs/<run_id>/tasks/<task_id>/context_snapshot.json
          │
          ├──► LAYER 2: TrajectoryRecord (stored verbatim)
          │    • cognition.analysis    ← verbatim
          │    • cognition.risks       ← verbatim
          │    • cognition.solution    ← verbatim
          │    • cognition.verification← verbatim
          │    • chosen / rejected code← verbatim
          │    → Appended to: data/trajectories.jsonl
          │
          └──► HOT → COLD seal
               • tar.zst the entire run/<run_id>/ directory
               • Delete plain run directory
               • ContextStore.load() decompresses on demand
```

### 10.7 Projected Storage (dual-layer + tar.zst)

| Per-run component | Naive inline | + Content-addressing | + tar.zst (cold) |
|:---|:---|:---|:---|
| Coordination prose | ~8 KB | ~8 KB | ~1.7 KB |
| Registry snapshots | ~18 KB | ~0.1 KB (version tags) | ~0.1 KB |
| Injected lesson text | ~5 KB | ~0.1 KB (IDs only) | ~0.1 KB |
| TaskMessage(s) | ~10 KB | ~0.1 KB (file refs) | ~0.1 KB |
| `cognition` blocks | ~6 KB | ~6 KB (verbatim) | ~1.3 KB |
| Code outputs | ~5 KB | ~5 KB (verbatim) | ~1.2 KB |
| **Total per run** | **~52 KB** | **~19 KB** | **~4.5 KB** |
| **1,000 runs** | ~52 MB | ~19 MB | **~4.5 MB** |
| **10,000 runs** | ~520 MB | ~190 MB | **~45 MB** |

The stacked approach achieves **~91% storage reduction** with full verbatim
training-critical data and complete reproducibility.

### 10.8 Updated `ExecutionResult` with Context Capture

Adds `context_snapshot_ref` to the schema from §3.7:

```json
{
  "schema_version": "2.0",
  "message_type": "execution_result",
  "run_id": "<uuid4>",
  "task_id": "t-001",
  "role": "coder | sysadmin",
  "status": "success | failure | partial",
  "context_snapshot_ref": "runs/<run_id>/tasks/t-001/context_snapshot.json",
  "outputs": {},
  "error": null,
  "cognition": {
    "analysis": "<VERBATIM — training critical>",
    "risks": "<VERBATIM — training critical>",
    "solution": "<VERBATIM — training critical>",
    "verification": "<VERBATIM — training critical>"
  },
  "telemetry": {
    "duration_ms": 0,
    "tool_calls_made": [],
    "tokens_per_second": 0,
    "context_tokens": 0,
    "model_used": "<model name>"
  }
}
```

### 10.9 Trajectory Record (Full Schema with Context Capture)

Stored in `sysadmin/data/trajectories.jsonl` — one JSON line per completed task:

```json
{
  "id": "traj-YYYYMMDD-HHMMSS-<rand>",
  "timestamp": "<ISO-8601 UTC>",
  "run_id": "<uuid4>",
  "task_id": "t-001",
  "role": "coder | sysadmin",
  "domain_tags": ["Defensive Bash Scripting"],
  "outcome": "approved | failed | aborted",
  "iterations": 2,
  "context_snapshot_ref": "runs/<run_id>/tasks/t-001/context_snapshot.json",
  "cognition": {
    "analysis": "<VERBATIM>",
    "risks": "<VERBATIM>",
    "solution": "<VERBATIM>",
    "verification": "<VERBATIM>"
  },
  "payload_type": "inline | diff_and_ref",
  "chosen": "<final script/code or null>",
  "rejected": "<prior iteration script/code or null>",
  "diff": "<unified diff or null>",
  "focused_snippet": "<±15 lines around failure point or null>",
  "raw_dir": "<relative path to raw files or null>",
  "reviewer_critique": "<last Reviewer or Security Gate critique>",
  "injected_lesson_ids": ["lesson-001"],
  "telemetry": {
    "eval_count": 459,
    "eval_duration_s": 4.71,
    "tokens_per_second": 97.5,
    "context_tokens": 1085,
    "model_used": "qwen2.5-coder:7b"
  }
}
```

### 10.10 CoT SFT Reconstruction

To reconstruct a training example from a trajectory record:

```python
def build_sft_example(traj: dict, context_store: ContextStore) -> dict:
    snapshot = context_store.load(traj["context_snapshot_ref"])
    system_prompt = context_store.load_by_hash(snapshot["system_prompt_hash"])
    lessons = context_store.load_lessons(snapshot["injected_lesson_ids"])
    task_message = context_store.load(snapshot["task_message_ref"])

    # Full input window (verbatim, uncompressed)
    user_input = task_message["description"]
    context_prefix = format_lessons(lessons) + format_rules(task_message["constraints"])

    # Full output (verbatim cognition + code)
    assistant_output = format_cot_response(
        analysis=traj["cognition"]["analysis"],
        risks=traj["cognition"]["risks"],
        solution=traj["cognition"]["solution"],
        code=traj["chosen"],
        verification=traj["cognition"]["verification"]
    )
    return {"system": system_prompt, "user": context_prefix + user_input,
            "assistant": assistant_output}
```

This gives full causal fidelity: the model learns *what context made this the right answer*,
not just *what the right answer was*.

### 10.11 Lossless Compression Layer (tar + zstd)

`tar + zstd` is lossless binary compression — safe on everything including verbatim
cognition and code. It operates entirely at rest, after execution completes, and is
transparent to all agents and the training pipeline.

> [!NOTE]
> `tar` alone does not compress — it only bundles files. Compression requires a
> compressor flag. **zstd** is the right choice for this workload:

| Compressor | Text/JSON ratio | Compress speed | Decompress speed | Verdict |
|:---|:---|:---|:---|:---|
| `gzip` (`-z`) | ~70–80% ↓ | Moderate | Fast | Usable, widely available |
| `zstd` (`--zstd`) | ~75–85% ↓ | **Very fast** | **Very fast** | ✅ Best fit — inference-time writes |
| `xz` (`-J`) | ~80–90% ↓ | Slow | Slow | Cold archival only |

Speed matters: run directories are sealed during/immediately after live inference.
zstd is ~5–10× faster than gzip at comparable ratios. Python 3.12+ supports
`tarfile.open(path, 'r:zst')` natively — no third-party package required.

#### Storage Tiers

```
  sysadmin/data/
  ├── runs/
  │   ├── <run_id>/           ← HOT: active run, plain JSON (read/write during execution)
  │   │   ├── state.json
  │   │   └── tasks/
  │   │       └── t-001/
  │   │           ├── task_message.json
  │   │           └── context_snapshot.json
  │   └── <run_id>.tar.zst   ← COLD: sealed after run completes (read-only)
  │
  ├── trajectories.jsonl      ← HOT: append-only, plain text (active training data)
  ├── trajectories.jsonl.zst  ← COLD: monthly archive of sealed JSONL chunks
  │
  └── registries/             ← WARM: versioned, compressed once per version change
      ├── tools_v2.0.json.zst
      ├── rules_v2.0.json.zst
      └── agents_v2.0.json.zst
```

**Hot → Cold lifecycle**:
1. Run completes → `state.json` set to `complete` or `aborted`
2. Compress entire run directory: `tar --zstd -cf runs/<run_id>.tar.zst runs/<run_id>/`
3. Delete plain directory: `rm -rf runs/<run_id>/`
4. `context_snapshot_ref` in `trajectories.jsonl` points to path inside the archive
5. `ContextStore.load()` transparently decompresses on demand

**JSONL archival** (monthly, for completed trajectory chunks):
```bash
# Seal current month's trajectories
tar --zstd -cf "trajectories_$(date +%Y-%m).tar.zst" \
    --files-from <(grep -l '"timestamp":"2026-09' trajectories.jsonl)
```

#### Compression Ratios for This Data

Text/JSON compresses significantly better than binary data:

```
  Component              Raw       zstd ratio   Compressed
  ─────────────────────────────────────────────────────────
  cognition blocks       ~6 KB       ~78% ↓      ~1.3 KB
  code / scripts         ~5 KB       ~76% ↓      ~1.2 KB
  coordination prose     ~8 KB       ~78% ↓      ~1.7 KB
  context_snapshot JSON  ~0.5 KB     ~70% ↓      ~0.15 KB
  ─────────────────────────────────────────────────────────
  Total per run (cold)   ~19 KB      ~76% ↓      ~4.5 KB
```

#### Stacked Storage Projections (both strategies combined: Content-Addressing + tar.zst)

| Strategy | Per-run | 1,000 runs | 10,000 runs |
|:---|:---|:---|:---|
| Naive inline | ~52 KB | ~52 MB | ~520 MB |
| + Content-addressing (§10.3) | ~19 KB | ~19 MB | ~190 MB |
| + tar.zst (hot→cold) | ~4.5 KB | ~4.5 MB | **~45 MB** |
| Reduction vs. naive | **91% ↓** | **91% ↓** | **91% ↓** |

~45 MB for 10,000 runs with full verbatim cognition, complete reproducibility,
and no semantic information loss.

#### `ContextStore` Transparent Decompression

The `ContextStore` class (to be implemented in `sysadmin/mcp_core/context_store.py`)
MUST transparently handle both hot (plain JSON) and cold (`.tar.zst`) refs:

```python
class ContextStore:
    def load(self, ref: str) -> dict:
        """Load context snapshot — transparent hot/cold handling."""
        archive = Path(ref).with_suffix('').with_suffix('') \
                           .parent.with_suffix('.tar.zst')
        if archive.exists():
            # Cold path: decompress on demand, no full extraction
            return self._load_from_archive(archive, ref)
        else:
            # Hot path: plain JSON
            return json.loads(Path(ref).read_text())

    def _load_from_archive(self, archive: Path, member: str) -> dict:
        import tarfile, io
        with tarfile.open(archive, 'r:zst') as tf:
            member_file = tf.extractfile(member)
            return json.loads(member_file.read())
```

> [!TIP]
> Use `tarfile.open(archive, 'r:zst')` with selective `extractfile()` for
> single-member reads — no need to decompress the entire archive to retrieve
> one context snapshot.

---

## 11. Relationship to Existing Architecture

| Dimension | Existing Sysadmin Pipeline | Arc-Orc-Rev v2 |
|:---|:---|:---|
| **Roles** | Orchestrator → Coder → Reviewer (3 roles) | All 6 taxonomy roles active |
| **Review scope** | Per-script execution loop | Whole-plan, pre-execution + Security Gate |
| **4-Pillar enforcement** | Output convention (PTY stream) | Structural schema field (machine-checkable) |
| **Domain tagging** | Via MemoryStore lesson categories | Enforced on every task via R-005 |
| **State** | SQLite conversation recall | External JSON run state by run_id |
| **Parallelism** | Sequential | DAG-based parallel dispatch |
| **Learning** | Positive + negative lesson extraction | Same, plus intra-task retry injection (§6.2, §9.1) |

Arc-Orc-Rev v2 is designed as the **planning and dispatch layer** that wraps the
existing `pipeline.py` execution loop. The Executor (Coder/Sysadmin) layer IS the
existing pipeline — Arc-Orc-Rev adds the pre-execution plan governance on top.

---

*Generated: 2026-09-06 | Draft RFC v7 — added Single-Model Multi-Persona (SMMP) execution profile*
