"""Unit tests for the multi-tier pre-execution code verification gates.

Tests:
1. Role specification prompt resolution for reviewer_code and security_code.
2. Reviewer code audit payload generation and rejection handling.
3. Security behavioral & STRIDE threat audit payload and rejection handling.
4. Tiered execution gating (Deterministic Linter -> Reviewer -> Security).
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from mcp_core.workspace import WORKSPACE_ROOT
from pipeline import (
    PipelineState,
    ContextStore,
    load_role_prompt,
    run_dispatch,
)


def test_role_prompt_resolution():
    """Verify that reviewer_code and security_code markdown files exist and load correctly."""
    rev_prompt = load_role_prompt("reviewer_code")
    assert "Reviewer Role Specification (Code Review Gate)" in rev_prompt
    assert "code_review_verdict" in rev_prompt

    sec_prompt = load_role_prompt("security_code")
    assert "Security Gate Role Specification (Behavioral & Code Threat Audit)" in sec_prompt
    assert "code_security_verdict" in sec_prompt


def test_dispatch_all_gates_pass(tmp_path):
    """Verify that when all 3 gates pass (linter, reviewer, security), the script is written and executed."""
    state = PipelineState("test-run-001", "Create a hello script")
    state.messages["annotated_plan"] = {
        "tasks": [
            {
                "task_id": "t-001",
                "description": "Create a defensive bash script",
                "domain_tags": ["Defensive Bash Scripting"],
                "assigned_agent": "coder",
                "tools_required": ["write_file"],
                "inputs": [],
                "outputs": ["sysadmin/test_script.sh"],
                "constraints": ["set -euo pipefail"],
            }
        ]
    }
    store = ContextStore()

    coder_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "execution_result",
        "run_id": "test-run-001",
        "task_id": "t-001",
        "role": "coder",
        "status": "success",
        "outputs": {
            "sysadmin/test_script.sh": (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "trap 'echo \"error\" >&2; exit 1' ERR\n"
                "echo \"Success\"\n"
                "exit 0\n"
            )
        },
        "cognition": {
            "analysis": "Create defensive bash script",
            "risks": "Risk of syntax error",
            "solution": "Add pipefail and ERR trap",
            "verification": "Test execution",
        },
    })

    reviewer_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "code_review_verdict",
        "run_id": "test-run-001",
        "task_id": "t-001",
        "verdict": "approved",
        "violations": [],
        "cognition": {
            "analysis": "Code adheres to prompt goals",
            "risks": "Minimal functional risk",
            "solution": "Approve for security audit",
            "verification": "Acceptance criteria met",
        },
    })

    security_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "code_security_verdict",
        "run_id": "test-run-001",
        "task_id": "t-001",
        "verdict": "cleared",
        "behavioral_summary": "Simple stdout echo without persistent side-effects",
        "threats": [],
        "cognition": {
            "analysis": "No STRIDE threats or elevation of privilege",
            "risks": "Zero risk to host",
            "solution": "Clear execution",
            "verification": "Sandboxed inside workspace",
        },
    })

    def mock_stage_chat(role, system_prompt, user_content, model):
        if role == "coder":
            return coder_response
        elif role == "reviewer":
            return reviewer_response
        elif role == "security":
            return security_response
        return "{}"

    with patch("pipeline.stage_chat", side_effect=mock_stage_chat), \
         patch("pipeline.handle_write_file", return_value="Wrote file") as mock_write, \
         patch("pipeline.handle_execute_task", return_value="Exit Code: 0\nSuccess") as mock_exec, \
         patch("pipeline.MemoryStore") as mock_mem:

        mock_mem_inst = MagicMock()
        mock_mem_inst.search_lessons.return_value = []
        mock_mem.return_value = mock_mem_inst

        run_dispatch(state, store)

        assert state.status == "complete"
        assert state.tasks["t-001"]["status"] == "success"
        mock_write.assert_called_once()
        mock_exec.assert_called_once()
        assert any(e["event"] == "code_reviewed" for e in state.events)
        assert any(e["event"] == "code_security_cleared" for e in state.events)


def test_dispatch_reviewer_rejection_remediation(tmp_path):
    """Verify that when Reviewer rejects, critique is passed to Coder for retry."""
    state = PipelineState("test-run-002", "Create a hello script")
    state.messages["annotated_plan"] = {
        "tasks": [
            {
                "task_id": "t-001",
                "description": "Create a defensive bash script",
                "domain_tags": ["Defensive Bash Scripting"],
                "assigned_agent": "coder",
                "tools_required": ["write_file"],
                "inputs": [],
                "outputs": ["sysadmin/test_script.sh"],
                "constraints": ["set -euo pipefail"],
            }
        ]
    }
    store = ContextStore()

    coder_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "execution_result",
        "run_id": "test-run-002",
        "task_id": "t-001",
        "role": "coder",
        "status": "success",
        "outputs": {
            "sysadmin/test_script.sh": (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "trap 'echo \"error\" >&2; exit 1' ERR\n"
                "echo \"Wrong output\"\n"
                "exit 0\n"
            )
        },
    })

    # Reviewer rejects on attempt 1, approves on attempt 2
    rev_call_count = 0
    def mock_stage_chat(role, system_prompt, user_content, model):
        nonlocal rev_call_count
        if role == "coder":
            return coder_response
        elif role == "reviewer":
            rev_call_count += 1
            if rev_call_count == 1:
                return json.dumps({
                    "schema_version": "2.0",
                    "message_type": "code_review_verdict",
                    "run_id": "test-run-002",
                    "task_id": "t-001",
                    "verdict": "rejected",
                    "violations": [{"type": "wrong_message", "description": "Expected Hello output"}],
                    "cognition": {"analysis": "a", "risks": "b", "solution": "c", "verification": "d"},
                })
            else:
                return json.dumps({
                    "schema_version": "2.0",
                    "message_type": "code_review_verdict",
                    "run_id": "test-run-002",
                    "task_id": "t-001",
                    "verdict": "approved",
                    "violations": [],
                    "cognition": {"analysis": "a", "risks": "b", "solution": "c", "verification": "d"},
                })
        elif role == "security":
            return json.dumps({
                "schema_version": "2.0",
                "message_type": "code_security_verdict",
                "run_id": "test-run-002",
                "task_id": "t-001",
                "verdict": "cleared",
                "behavioral_summary": "Safe",
                "threats": [],
                "cognition": {"analysis": "a", "risks": "b", "solution": "c", "verification": "d"},
            })
        return "{}"

    with patch("pipeline.stage_chat", side_effect=mock_stage_chat), \
         patch("pipeline.handle_write_file", return_value="Wrote file") as mock_write, \
         patch("pipeline.handle_execute_task", return_value="Exit Code: 0\nSuccess") as mock_exec, \
         patch("pipeline.MemoryStore") as mock_mem:

        mock_mem_inst = MagicMock()
        mock_mem_inst.search_lessons.return_value = []
        mock_mem.return_value = mock_mem_inst

        run_dispatch(state, store)

        assert state.tasks["t-001"]["retries"] == 1
        assert state.tasks["t-001"]["status"] == "success"
        assert any(e["event"] == "code_review_rejected" for e in state.events)
        assert any(e["event"] == "code_reviewed" for e in state.events)


def test_dispatch_security_rejection_halts_write(tmp_path):
    """Verify that when Security rejects, the file is NOT written or executed."""
    state = PipelineState("test-run-003", "Create an unsafe script")
    state.messages["annotated_plan"] = {
        "tasks": [
            {
                "task_id": "t-001",
                "description": "Create a script with dangerous behavioral side-effects",
                "domain_tags": ["Defensive Bash Scripting"],
                "assigned_agent": "coder",
                "tools_required": ["write_file"],
                "inputs": [],
                "outputs": ["sysadmin/unsafe.sh"],
                "constraints": ["set -euo pipefail"],
            }
        ]
    }
    store = ContextStore()

    coder_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "execution_result",
        "run_id": "test-run-003",
        "task_id": "t-001",
        "role": "coder",
        "status": "success",
        "outputs": {
            "sysadmin/unsafe.sh": (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "trap 'echo \"error\" >&2; exit 1' ERR\n"
                "sudo rm -rf /var/log/*\n"
                "exit 0\n"
            )
        },
    })

    reviewer_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "code_review_verdict",
        "run_id": "test-run-003",
        "task_id": "t-001",
        "verdict": "approved",
        "violations": [],
        "cognition": {"analysis": "a", "risks": "b", "solution": "c", "verification": "d"},
    })

    security_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "code_security_verdict",
        "run_id": "test-run-003",
        "task_id": "t-001",
        "verdict": "rejected",
        "behavioral_summary": "Attempts destructive log deletion with sudo privilege escalation",
        "threats": [
            {
                "category": "Elevation of Privilege",
                "description": "Use of sudo violates unprivileged execution rule R-004",
            }
        ],
        "cognition": {"analysis": "a", "risks": "b", "solution": "c", "verification": "d"},
    })

    def mock_stage_chat(role, system_prompt, user_content, model):
        if role == "coder":
            return coder_response
        elif role == "reviewer":
            return reviewer_response
        elif role == "security":
            return security_response
        return "{}"

    with patch("pipeline.stage_chat", side_effect=mock_stage_chat), \
         patch("pipeline.handle_write_file", return_value="Wrote file") as mock_write, \
         patch("pipeline.handle_execute_task", return_value="Exit Code: 0\nSuccess") as mock_exec, \
         patch("pipeline.MemoryStore") as mock_mem:

        mock_mem_inst = MagicMock()
        mock_mem_inst.search_lessons.return_value = []
        mock_mem.return_value = mock_mem_inst

        run_dispatch(state, store)

        # Retries exhausted -> failed; write and execute MUST NOT have been called
        assert state.tasks["t-001"]["status"] == "failed"
        mock_write.assert_not_called()
        mock_exec.assert_not_called()
        assert any(e["event"] == "code_security_rejected" for e in state.events)


def test_dispatch_two_task_dag_executes_only_once_by_sysadmin(tmp_path):
    """Verify that in a 2-task DAG (coder creates, sysadmin executes), the script is executed exactly once by sysadmin."""
    state = PipelineState("test-run-004", "Create and execute hello script")
    state.messages["annotated_plan"] = {
        "tasks": [
            {
                "task_id": "t-001",
                "description": "Create a defensive bash script at sysadmin/hello_world.sh",
                "domain_tags": ["Defensive Bash Scripting"],
                "assigned_agent": "coder",
                "tools_required": ["write_file"],
                "inputs": [],
                "outputs": ["sysadmin/hello_world.sh"],
                "constraints": ["set -euo pipefail"],
            },
            {
                "task_id": "t-002",
                "description": "Execute the bash script at sysadmin/hello_world.sh and verify output",
                "domain_tags": ["Defensive Bash Scripting"],
                "assigned_agent": "sysadmin",
                "tools_required": ["run_bash"],
                "inputs": ["sysadmin/hello_world.sh"],
                "outputs": ["hello_world_result"],
                "constraints": [],
            }
        ]
    }
    store = ContextStore()

    coder_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "execution_result",
        "run_id": "test-run-004",
        "task_id": "t-001",
        "role": "coder",
        "status": "success",
        "outputs": {
            "sysadmin/hello_world.sh": (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "trap 'echo \"error\" >&2; exit 1' ERR\n"
                "echo \"Hello\"\n"
                "exit 0\n"
            )
        },
    })

    sysadmin_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "execution_result",
        "run_id": "test-run-004",
        "task_id": "t-002",
        "role": "sysadmin",
        "status": "success",
        "outputs": {"stdout": "Hello\n"},
    })

    reviewer_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "code_review_verdict",
        "run_id": "test-run-004",
        "task_id": "t-001",
        "verdict": "approved",
        "violations": [],
        "cognition": {"analysis": "a", "risks": "b", "solution": "c", "verification": "d"},
    })

    security_response = json.dumps({
        "schema_version": "2.0",
        "message_type": "code_security_verdict",
        "run_id": "test-run-004",
        "task_id": "t-001",
        "verdict": "cleared",
        "behavioral_summary": "Safe",
        "threats": [],
        "cognition": {"analysis": "a", "risks": "b", "solution": "c", "verification": "d"},
    })

    def mock_stage_chat(role, system_prompt, user_content, model):
        if role == "coder":
            return coder_response
        elif role == "sysadmin":
            return sysadmin_response
        elif role == "reviewer":
            return reviewer_response
        elif role == "security":
            return security_response
        return "{}"

    with patch("pipeline.stage_chat", side_effect=mock_stage_chat), \
         patch("pipeline.handle_write_file", return_value="Wrote file") as mock_write, \
         patch("pipeline.handle_execute_task", return_value="Exit Code: 0\nHello") as mock_exec, \
         patch("pipeline.MemoryStore") as mock_mem:

        mock_mem_inst = MagicMock()
        mock_mem_inst.search_lessons.return_value = []
        mock_mem.return_value = mock_mem_inst

        run_dispatch(state, store)

        # Coder wrote the file
        mock_write.assert_called_once()

        # The script was executed EXACTLY ONCE (in t-002 by sysadmin, not in t-001 by coder)
        assert mock_exec.call_count == 1
        assert state.tasks["t-001"]["status"] == "success"
        assert state.tasks["t-002"]["status"] == "success"

