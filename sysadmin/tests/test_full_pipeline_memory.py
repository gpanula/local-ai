"""Unit tests for full pipeline memory injection, dynamic rubrics, and lesson extraction."""

import json
import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from mcp_core.memory import MemoryStore
from mcp_core.context_store import ContextStore
from pipeline import (
    PipelineState,
    run_architect,
    run_orchestrator,
    run_reviewer,
    run_security,
    _finalize_pipeline_run,
)


@pytest.fixture
def temp_workspace(tmp_path):
    """Fixture providing isolated temporary directories for db and runs."""
    db_path = str(tmp_path / "test_memory.db")
    runs_dir = str(tmp_path / "runs")
    traj_path = str(tmp_path / "trajectories.jsonl")
    os.makedirs(runs_dir, exist_ok=True)

    # Initialize store with seed lessons
    with MemoryStore(db_path) as mem:
        mem.insert_lesson({
            "id": "lesson-arch-01",
            "category": "System Architecture",
            "keywords": ["architecture", "decomposition", "modular"],
            "rule": "Decompose system services into single-responsibility units with decoupled data flow.",
            "lesson_type": "solved_pattern",
        })
        mem.insert_lesson({
            "id": "lesson-orc-01",
            "category": "Multi-Agent Orchestration",
            "keywords": ["orchestrator", "dag", "scheduling"],
            "rule": "Ensure DAG edges specify data_dependency for dependent tasks.",
            "lesson_type": "solved_pattern",
        })
        mem.insert_lesson({
            "id": "lesson-rev-01",
            "category": "Code Quality Toolchain",
            "keywords": ["audit", "shellcheck", "review"],
            "rule": "Check that scripts enforce set -euo pipefail and traps.",
            "lesson_type": "solved_pattern",
        })
        mem.insert_lesson({
            "id": "lesson-sec-01",
            "category": "Security & Hardening",
            "keywords": ["stride", "sandbox", "security"],
            "rule": "Validate that command paths avoid ambient PATH resolution.",
            "lesson_type": "solved_pattern",
        })

    yield {
        "db_path": db_path,
        "runs_dir": runs_dir,
        "traj_path": traj_path,
        "store": ContextStore(runs_dir=runs_dir),
    }


def test_architect_memory_injection(temp_workspace):
    """Test Architect queries and injects relevant System Architecture lessons."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    state = PipelineState("run-arch-test", "Design a modular architecture pipeline")

    mock_plan = {
        "run_id": "run-arch-test",
        "tasks": [{"task_id": "t-001", "description": "Write service", "domain_tags": ["System Architecture"]}],
    }

    with patch("pipeline.DEFAULT_DB_PATH", db_path), \
         patch("pipeline.stage_chat", return_value=json.dumps(mock_plan)) as mock_chat:
        next_phase = run_architect(state, store)

        assert next_phase == "orchestrator"
        assert "architect" in state.injected_lessons
        injected = state.injected_lessons["architect"]
        assert len(injected) > 0
        assert any(l["id"] == "lesson-arch-01" for l in injected)

        # Verify payload passed to stage_chat contains architectural_guidance
        call_args = mock_chat.call_args[1]
        user_content = json.loads(call_args["user_content"])
        assert "architectural_guidance" in user_content
        assert "Decompose system services" in user_content["architectural_guidance"]
        assert any(l["id"] == "lesson-arch-01" for l in user_content.get("injected_lessons", []))


def test_architect_budget_exhaustion_hard_failure(temp_workspace):
    """Test Architect budget exhaustion stages a hard_failure lesson."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    state = PipelineState("run-arch-exhaust", "Complex prompt")
    state.architect_revisions_used = 3  # budget is 3
    state.messages["review_verdict"] = {"verdict": "rejected", "violations": ["Too vague"]}

    with patch("pipeline.DEFAULT_DB_PATH", db_path):
        next_phase = run_architect(state, store)
        assert next_phase == "aborted"
        assert state.status == "aborted"

        with MemoryStore(db_path) as mem:
            pending = mem.list_pending_lessons()
            assert len(pending) == 1
            assert pending[0]["lesson_type"] == "hard_failure"
            assert pending[0]["category"] == "System Architecture"
            assert "Architect revision budget exhausted" in pending[0]["proposed_rule"]


def test_orchestrator_memory_injection(temp_workspace):
    """Test Orchestrator queries and injects Multi-Agent Orchestration lessons."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    state = PipelineState("run-orc-test", "Orchestrate multi-agent DAG")
    state.messages["plan"] = {
        "tasks": [{"task_id": "t-001", "description": "Execute script", "domain_tags": ["Multi-Agent Orchestration"]}],
    }

    mock_annotated = {
        "run_id": "run-orc-test",
        "tasks": [{"task_id": "t-001", "assigned_agent": "sysadmin", "domain_tags": ["Multi-Agent Orchestration"]}],
        "dag": {"nodes": ["t-001"], "edges": []},
    }

    with patch("pipeline.DEFAULT_DB_PATH", db_path), \
         patch("pipeline.stage_chat", return_value=json.dumps(mock_annotated)) as mock_chat:
        next_phase = run_orchestrator(state, store)

        assert next_phase == "reviewer"
        assert "orchestrator" in state.injected_lessons
        injected = state.injected_lessons["orchestrator"]
        assert any(l["id"] == "lesson-orc-01" for l in injected)

        call_args = mock_chat.call_args[1]
        user_content = json.loads(call_args["user_content"])
        assert "orchestration_guidance" in user_content
        assert "Ensure DAG edges specify" in user_content["orchestration_guidance"]
        assert any(l["id"] == "lesson-orc-01" for l in user_content.get("injected_lessons", []))


def test_orchestrator_budget_exhaustion_hard_failure(temp_workspace):
    """Test Orchestrator budget exhaustion stages a hard_failure lesson."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    state = PipelineState("run-orc-exhaust", "Complex prompt")
    state.orchestrator_revisions_used = 3  # budget is 3
    state.messages["review_verdict"] = {"verdict": "rejected", "violations": ["Cycle in DAG"]}

    with patch("pipeline.DEFAULT_DB_PATH", db_path):
        next_phase = run_orchestrator(state, store)
        assert next_phase == "aborted"
        assert state.status == "aborted"

        with MemoryStore(db_path) as mem:
            pending = mem.list_pending_lessons()
            assert len(pending) == 1
            assert pending[0]["lesson_type"] == "hard_failure"
            assert pending[0]["category"] == "Multi-Agent Orchestration"
            assert "Orchestrator revision budget exhausted" in pending[0]["proposed_rule"]


def test_reviewer_and_security_dynamic_rubrics(temp_workspace):
    """Test Reviewer and Security inject dynamic heuristics into annotated_plan."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    state = PipelineState("run-rubrics-test", "Test prompt")
    state.messages["annotated_plan"] = {
        "run_id": "run-rubrics-test",
        "tasks": [{"task_id": "t-001", "description": "Create test script", "domain_tags": ["Defensive Bash Scripting"], "assigned_agent": "coder"}],
        "dag": {"nodes": ["t-001"], "edges": []},
    }

    mock_review_verdict = {"run_id": "run-rubrics-test", "verdict": "approved", "critique": "Looks good"}
    mock_sec_verdict = {"run_id": "run-rubrics-test", "verdict": "cleared", "threat_model": {}}

    with patch("pipeline.DEFAULT_DB_PATH", db_path), \
         patch("pipeline.validate_annotated_plan", return_value={"verdict": "approved"}), \
         patch("pipeline.stage_chat") as mock_chat:

        mock_chat.return_value = json.dumps(mock_review_verdict)
        next_phase = run_reviewer(state, store)
        assert next_phase == "security"
        assert "reviewer" in state.injected_lessons
        assert "audit_heuristics" in state.messages["annotated_plan"]
        assert len(state.messages["annotated_plan"]["audit_heuristics"]) > 0

        mock_chat.return_value = json.dumps(mock_sec_verdict)
        next_phase_sec = run_security(state, store)
        assert next_phase_sec == "dispatch"
        assert "security" in state.injected_lessons
        assert "security_heuristics" in state.messages["annotated_plan"]
        assert len(state.messages["annotated_plan"]["security_heuristics"]) > 0


def test_security_clearance_with_remediation(temp_workspace):
    """Test Security clearance after revisions extracts and stages a solved_pattern lesson."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    state = PipelineState("run-remediation-test", "Fix bash permissions")
    state.architect_revisions_used = 1
    state.messages["review_verdict"] = {
        "verdict": "rejected",
        "violations": [{"type": "security", "description": "Unescaped variable in script path"}],
    }
    state.messages["annotated_plan"] = {
        "run_id": "run-remediation-test",
        "tasks": [{"task_id": "t-001", "assigned_agent": "coder", "domain_tags": ["Defensive Bash Scripting"]}],
    }

    mock_sec_verdict = {"run_id": "run-remediation-test", "verdict": "cleared"}

    with patch("pipeline.DEFAULT_DB_PATH", db_path), \
         patch("pipeline.stage_chat", return_value=json.dumps(mock_sec_verdict)), \
         patch("pipeline.extract_lesson_from_critique") as mock_extract:

        mock_extract.return_value = {
            "proposed_rule": "Always quote variables in script paths to prevent injection",
            "category": "System Architecture",
            "keywords": ["security", "variable", "path"],
            "task_file": "runs/run-remediation-test/messages/annotated_plan.json",
            "reviewer_critique": "Unescaped variable in script path",
            "lesson_type": "solved_pattern",
            "outcome": "cleared",
        }

        next_phase = run_security(state, store)
        assert next_phase == "dispatch"
        assert mock_extract.called

        with MemoryStore(db_path) as mem:
            pending = mem.list_pending_lessons()
            assert len(pending) == 1
            assert pending[0]["lesson_type"] == "solved_pattern"
            assert "quote variables" in pending[0]["proposed_rule"]


def test_security_clearance_clean_first_pass(temp_workspace):
    """Test clean first-pass clearance attributes +1 utility to all planning lessons."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    state = PipelineState("run-clean-test", "Clean task")
    state.architect_revisions_used = 0
    state.orchestrator_revisions_used = 0
    state.injected_lessons["architect"] = [{"id": "lesson-arch-01"}]
    state.injected_lessons["orchestrator"] = [{"id": "lesson-orc-01"}]
    state.messages["annotated_plan"] = {
        "run_id": "run-clean-test",
        "tasks": [{"task_id": "t-001", "assigned_agent": "coder", "domain_tags": ["Defensive Bash Scripting"]}],
    }

    mock_sec_verdict = {"run_id": "run-clean-test", "verdict": "cleared"}

    with patch("pipeline.DEFAULT_DB_PATH", db_path), \
         patch("pipeline.stage_chat", return_value=json.dumps(mock_sec_verdict)):

        next_phase = run_security(state, store)
        assert next_phase == "dispatch"

        with MemoryStore(db_path) as mem:
            l_arch = mem.get_lesson("lesson-arch-01")
            assert l_arch["prevented_rework_count"] == 1
            l_orc = mem.get_lesson("lesson-orc-01")
            assert l_orc["prevented_rework_count"] == 1


def test_finalize_pipeline_trajectory_and_positive_mining(temp_workspace):
    """Test _finalize_pipeline_run writes trajectory and mines proven_pattern on clean run."""
    db_path = temp_workspace["db_path"]
    store = temp_workspace["store"]
    traj_path = temp_workspace["traj_path"]

    state = PipelineState("run-fin-test", "Clean pipeline run")
    state.status = "complete"
    state.architect_revisions_used = 0
    state.orchestrator_revisions_used = 0
    state.tasks["t-001"] = {"status": "success", "retries": 0, "role": "coder"}
    state.injected_lessons["t-001"] = [{"id": "lesson-arch-01"}]

    # Save mock messages with rich cognition for reviewer and security
    state.messages["review_verdict"] = {
        "verdict": "approved",
        "cognition": {
            "analysis": "Reviewer audit passed all structural checks",
            "risks": "No deadlocks in task execution graph",
            "solution": "Approve annotated plan",
            "verification": "Linter assertions verified",
            "chain_of_thought": "Verifying DAG acyclicity and tool arguments",
        },
    }
    state.messages["security_verdict"] = {
        "verdict": "cleared",
        "cognition": {
            "analysis": "STRIDE threat modeling conducted across all categories",
            "risks": "No privilege escalation or path traversal risks detected",
            "solution": "Clear plan for dispatch",
            "verification": "Sandbox constraints confirmed",
            "chain_of_thought": "Checking file write destinations against allowed workspace",
        },
    }

    # Save mock execution result with rich cognition
    store.save_message(state.run_id, "execution_result_t-001", {
        "status": "success",
        "artifacts": {"test.sh": "#!/bin/bash\necho hello\n"},
        "cognition": {
            "analysis": "Root cause analysis",
            "risks": "Potential permission collision if file already exists in directory without write bits",
            "solution": "Check write permission before open and set umask 027 proactively",
            "verification": "Assert exit code 0",
            "chain_of_thought": "Reasoning about file permissions and trap handling",
        },
    })

    with patch("pipeline.DEFAULT_DB_PATH", db_path), \
         patch("pipeline.DEFAULT_TRAJECTORIES_PATH", traj_path):

        _finalize_pipeline_run(state, store, model="winter-prime:latest")

        # Verify trajectory recorded
        assert os.path.exists(traj_path)
        with open(traj_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 1
        assert lines[0]["prompt"] == "Clean pipeline run"
        assert lines[0]["outcome"] == "approved"
        assert "lesson-arch-01" in lines[0]["injected_lessons"]
        assert lines[0]["reasoning"]["strategy"] == "Root cause analysis"
        assert lines[0]["reasoning"]["chain_of_thought"] == "Reasoning about file permissions and trap handling"
        assert "Potential permission collision" in lines[0]["reasoning"]["risks"]
        assert lines[0]["roles"]["coder"]["solution"] == "Check write permission before open and set umask 027 proactively"
        assert lines[0]["roles"]["coder"]["chain_of_thought"] == "Reasoning about file permissions and trap handling"
        assert lines[0]["roles"]["reviewer"]["analysis"] == "Reviewer audit passed all structural checks"
        assert lines[0]["roles"]["reviewer"]["chain_of_thought"] == "Verifying DAG acyclicity and tool arguments"
        assert lines[0]["roles"]["security"]["analysis"] == "STRIDE threat modeling conducted across all categories"
        assert lines[0]["roles"]["security"]["chain_of_thought"] == "Checking file write destinations against allowed workspace"

        # Verify proactive risk mitigation was mined into proven_pattern
        with MemoryStore(db_path) as mem:
            pending = mem.list_pending_lessons()
            assert len(pending) == 1
            assert pending[0]["lesson_type"] == "proven_pattern"
            assert "Proactive risk mitigation" in pending[0]["proposed_rule"]
            assert pending[0]["category"] == "Defensive Bash Scripting"
