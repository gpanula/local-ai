# Lessons Learned — Episodic Memory Store

> **Purpose**: Git-canonical store of approved episodic lessons, promoted from the
> pending review queue via the `review-lessons` CLI. Each lesson is a YAML-frontmatter
> block followed by the rule text.
>
> **Format** (see `ai_memory_summary.md` §Canonical File Formats):
>
> ```markdown
> ---
> id: lesson-YYYYMMDD-NN
> category: <category>
> keywords: [kw1, kw2, kw3]
> created: YYYY-MM-DD
> source_task: <path/to/prompt.md>
> ---
> **Rule**: <rule text>
> ```

<!-- Lessons are appended below this line by the review-lessons promotion flow. -->

---
id: lesson-20260830-03
category: Binary Isolation
keywords: [ansible, ansible sandbox isolation, bash, bash scripting, binary assertions, binary existence check, binary isolation, code quality, functional test suites, linters, pre-execution assertions, pre-flight linters, python, python syntax validation, virtual environment, yaml, yaml parsing]
created: 2026-08-30
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: When developing a standalone, portable Bash verification script for code quality and pre-flight linters toolchain, ensure that the script resolves the virtual environment path deterministically and safely. Also, explicitly invoke all required binaries from the virtual environment's bin directory to maintain binary isolation. Before executing functional test suites, assert that all required binaries exist and are executable.

---
id: lesson-20260830-13
category: ShellCheck
keywords: [codes, linter, loop, pre-flight, sc1003, sc1009, sc1050, sc1064, sc1065, sc1072, sc1073, sc1078, sc1079, sc2034, shellcheck, stuck, styleguidelines, variablenaming]
created: 2026-08-30
source_task: sysadmin/prompts/verify_code_quality_toolchain.md
---
**Rule**: Ensure that all ShellCheck linter findings (SC1003, SC1009, SC1050, SC1064, SC1065, SC1072, SC1073, SC1078, SC1079) are addressed in the `sysadmin/prompts/verify_code_quality_toolchain.sh` script before deployment.

---
id: lesson-20260830-14
category: Docker Orchestration
keywords: [docker, compose]
created: 2026-08-30
source_task: 
---
**Rule**: Always check docker daemon health before running compose.

---
id: lesson-20260918-01
category: Defensive Bash Scripting
keywords: [error handling, traps, environment variables, path resolution]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Implement robust error handling, environment variable resolution, and resource cleanup traps in scripts to ensure reliability and compliance with operational standards.

---
id: lesson-20260918-02
category: Binary Isolation
keywords: [ERR Trap, Exit Code 0, Success Message, Virtual Environment, Binary Existence]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Implement ERR trap for error diagnostics, explicitly exit 0 on success, include success message with required emoji, resolve REPO_ROOT/VENV_DIR variables, and verify binary existence via [ -x "${VENV_DIR}/bin/shellcheck" ] before execution.

---
id: lesson-20260918-03
category: Defensive Bash Scripting
keywords: [success message, environment variables, error handling, exit code 0]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Ensure scripts use the correct success message matching task requirements, resolve all required environment variables (REPO_ROOT/VENV_DIR) deterministically, and guard success messages with explicit error checks to guarantee exit code 0 compliance

---
id: lesson-20260918-04
category: Defensive Bash Scripting
keywords: [success message, exact output, required string, script output]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Ensure the script's success message exactly matches the specified output in the task prompt, including case and punctuation. Verify the output string against the implementation contract requirements before finalizing the script.

---
id: lesson-20260918-05
category: Defensive Bash Scripting
keywords: [virtual environment resolution, binary existence assertion, EXIT trap]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Always resolve REPO_ROOT and VENV_DIR deterministically, assert existence of binaries via explicit paths, and implement EXIT traps for cleanup to comply with universal system rules and defensive standards.

---
id: lesson-20260918-06
category: Binary Isolation
keywords: [virtual environment, REPO_ROOT, VENV_DIR, Rule #1, binary resolution]
created: 2026-09-18
source_task: sysadmin/prompts/hello_world_test.md
---
**Rule**: Mandate resolution of REPO_ROOT and VENV_DIR per Rule #1, and assert existence of required binaries (e.g., shellcheck) before use. Example: Resolve REPO_ROOT using $(git rev-parse --show-toplevel) and set VENV_DIR=${REPO_ROOT}/venv, then check [ -f ${VENV_DIR}/bin/shellcheck ] before execution.

---
id: lesson-20260918-07
category: unknown
keywords: [schema_version, message_type, review_verdict, run_id, test-run-mock-002]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: {"schema_version": "2.0", "message_type": "review_verdict", "run_id": "test-run-mock-002", "verdict": "approved", "return_to": null, "violations": [], "cognition": {"analysis": "Audit pass", "risks": "No risks", "solution": "Approve", "verification": "Verified"}}

---
id: lesson-20260918-08
category: unknown
keywords: [schema_version, message_type, review_verdict, run_id, test-run-mock-002]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: {"schema_version": "2.0", "message_type": "review_verdict", "run_id": "test-run-mock-002", "verdict": "approved", "return_to": null, "violations": [], "cognition": {"analysis": "Audit pass", "risks": "No risks", "solution": "Approve", "verification": "Verified"}}

---
id: lesson-20260918-09
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, coder]
created: 2026-09-18
source_task: runs/run-20260909-043422-8fc76f/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for coder: Potential risks include script failures due to missing dependencies or incorrect environment variabl -> Solved via: The solution involves embedding the bash script directly in the output, ensuring it adheres to defen

---
id: lesson-20260918-10
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs that receive an 'audit pass' with no reported risks should be automatically approved.

---
id: lesson-20260918-11
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-12
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-13
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, coder]
created: 2026-09-18
source_task: runs/run-20260916-041133-286ca9/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for coder: Potential risks include script failures and incorrect exit codes. Defensive safeguards ensure the sc -> Solved via: The script is embedded directly in the output, ensuring it's self-contained and compliant with defen

---
id: lesson-20260918-14
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-15
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs that receive an audit pass with no identified risks should be automatically approved.

---
id: lesson-20260918-16
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-17
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs that receive an 'audit pass' with no reported risks should be automatically approved.

---
id: lesson-20260918-18
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-19
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, coder]
created: 2026-09-18
source_task: runs/run-20260916-042533-3b3b50/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for coder: Potential edge cases, exit codes, and defensive safeguards -> Solved via: Exact code authored and file written

---
id: lesson-20260918-20
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-21
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-22
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, coder]
created: 2026-09-18
source_task: runs/run-20260916-044817-ea9894/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for coder: Potential edge cases include script failures and incorrect exit codes. Defensive safeguards include  -> Solved via: Script content embedded directly to ensure compliance with defensive standards.

---
id: lesson-20260918-23
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs that receive an audit pass with no identified risks should be automatically approved.

---
id: lesson-20260918-24
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-25
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no risks should be automatically approved.

---
id: lesson-20260918-26
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-27
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no risks should be automatically approved.

---
id: lesson-20260918-28
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs that receive an 'audit pass' with no reported risks should be automatically approved.

---
id: lesson-20260918-29
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no risks should be automatically approved.

---
id: lesson-20260918-30
category: Script Creation and Execution
keywords: [bash script, defensive standards, exit cleanly, write_file tool]
created: 2026-09-18
source_task: runs/run-20260916-054359-6e3734/messages/annotated_plan.json
---
**Rule**: Create a bash script using the `write_file` tool with the necessary content, enable defensive standards, and ensure it exits with code 0 when executed.

---
id: lesson-20260918-31
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-32
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-33
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-34
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-35
category: Defensive Bash Scripting
keywords: [Unicode, success message, bash script]
created: 2026-09-18
source_task: # Task: Hello World Multi-Agent Pipeline Test

## Goal
Write and execute a standalone bash script at
---
**Rule**: Ensure that success messages in bash scripts use the correct Unicode character. For instance, use '\ud83c\udf89' for a party popper emoji instead of '\u274c' for a cross mark.

---
id: lesson-20260918-36
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-37
category: Security & Hardening
keywords: [bash script, defensive standards, risk mitigation, tool verification]
created: 2026-09-18
source_task: runs/run-20260918-042512-51805f/messages/annotated_plan.json
---
**Rule**: Ensure all bash scripts include defensive measures such as set -euo pipefail, ERR traps, and proper exit codes, and verify that execution tools like run_bash are permitted and sandboxed to prevent unsafe operations.

---
id: lesson-20260918-38
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-39
category: Multi-Agent Orchestration
keywords: [orchestrator, budget, dag, scheduling]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/annotated_plan.json
---
**Rule**: Orchestrator revision budget exhausted after 3 attempts for: Review security configuration

---
id: lesson-20260918-40
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-41
category: Multi-Agent Orchestration
keywords: [orchestrator, budget, dag, scheduling]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/annotated_plan.json
---
**Rule**: Orchestrator revision budget exhausted after 3 attempts for: Review security configuration

---
id: lesson-20260918-42
category: Audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no identified risks should be approved.

---
id: lesson-20260918-43
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-44
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs that receive an 'audit pass' with 'no risks' should be automatically approved.

---
id: lesson-20260918-45
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-46
category: ShellCheck
keywords: [ShellCheck, SC2086, double quotes, globbing, word splitting]
created: 2026-09-18
source_task: # Task Specification: Verify Code Quality & Pre-Flight Linters Toolchain

## Objective
Author and ex
---
**Rule**: Always use double quotes around variables in shell scripts to prevent globbing and word splitting, as recommended by ShellCheck.

---
id: lesson-20260918-47
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no risks should be automatically approved.

---
id: lesson-20260918-48
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-49
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-50
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-51
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs should be audited for risks and approved only if no risks are identified.

---
id: lesson-20260918-52
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-53
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no risks should be automatically approved.

---
id: lesson-20260918-54
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-55
category: Multi-Agent Orchestration
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All pipeline runs that receive an 'audit pass' with 'no risks' should be automatically approved.

---
id: lesson-20260918-56
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-57
category: audit
keywords: [audit pass, no risks, approved]
created: 2026-09-18
source_task: runs/test-run-mock-002/messages/annotated_plan.json
---
**Rule**: All audit passes with no risks should be automatically approved.

---
id: lesson-20260918-58
category: Defensive Bash Scripting
keywords: [proactive, risk, mitigation, sysadmin]
created: 2026-09-18
source_task: runs/test-dynamic-auditor-001/messages/execution_result_t-001.json
---
**Rule**: Proactive risk mitigation for sysadmin: Zero environmental side effects or unwanted state changes observed. -> Solved via: Completed defensive audit task and generated structured output.

---
id: lesson-20260918-59
category: ShellCheck
keywords: [ShellCheck, SC2046, SC2086, quoting, word splitting, globbing]
created: 2026-09-18
source_task: # Task Specification: Verify Code Quality & Pre-Flight Linters Toolchain

## Objective
Author and ex
---
**Rule**: Always quote variables to prevent word splitting and globbing in shell scripts. Use double quotes for variables that contain spaces or special characters.
