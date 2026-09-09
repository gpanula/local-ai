"""Unit tests for sysadmin.validator (Deterministic Pre-Filter)."""

import copy
import pytest

from validator import (
    check_schema,
    check_tools,
    check_agents,
    check_domain_tags,
    check_dag,
    check_prompt_fidelity,
    check_cognition_substance,
    validate_annotated_plan,
    validate_code_output,
    load_tool_registry,
    load_agent_registry,
    load_taxonomy,
)


@pytest.fixture
def frozen_prompt() -> str:
    return "Create a defensive bash script for automated backups."


@pytest.fixture
def valid_plan(frozen_prompt: str) -> dict:
    return {
        "schema_version": "2.0",
        "message_type": "annotated_plan",
        "run_id": "test-run-1234",
        "revision": 0,
        "original_prompt": frozen_prompt,
        "goal_summary": "Automated backup script with error handling",
        "dag": {
            "nodes": ["t-001", "t-002"],
            "edges": [{"from": "t-001", "to": "t-002", "type": "data_dependency"}],
        },
        "tasks": [
            {
                "task_id": "t-001",
                "description": "Analyze backup storage paths and permissions",
                "domain_tags": ["Defensive Bash Scripting"],
                "assigned_agent": "sysadmin",
                "assigned_model": "qwen2.5-coder:7b",
                "tools_required": ["run_bash"],
                "inputs": [],
                "outputs": ["backup_dir_verified"],
                "constraints": [],
            },
            {
                "task_id": "t-002",
                "description": "Generate backup script adhering to defensive standards",
                "domain_tags": ["Defensive Bash Scripting", "Binary Isolation"],
                "assigned_agent": "coder",
                "assigned_model": "qwen2.5-coder:7b",
                "tools_required": ["run_bash"],
                "inputs": ["t-001"],
                "outputs": ["backup.sh"],
                "constraints": [],
            },
        ],
        "cognition": {
            "analysis": "Pillar 1: Root-cause deconstruction and backup requirements analysis.",
            "risks": "Pillar 2: Potential data corruption or permission denial during backup execution.",
            "solution": "Pillar 3: Two-stage execution with dry-run verification before backup run.",
            "verification": "Pillar 4: Verify exit code 0 and existence of backup archive on target storage.",
        },
    }


def test_check_schema_missing_key(valid_plan: dict):
    plan = copy.deepcopy(valid_plan)
    del plan["dag"]
    violations = check_schema(plan)
    assert any(v["type"] == "schema_error" and "dag" in v["description"] for v in violations)

    plan2 = copy.deepcopy(valid_plan)
    del plan2["tasks"][0]["tools_required"]
    violations2 = check_schema(plan2)
    assert any(v["type"] == "schema_error" and "tools_required" in v["description"] for v in violations2)


def test_check_tools_invalid(valid_plan: dict):
    tool_reg = load_tool_registry()
    plan = copy.deepcopy(valid_plan)
    plan["tasks"][0]["tools_required"].append("arbitrary_dangerous_tool")
    violations = check_tools(plan, tool_reg)
    assert len(violations) == 1
    assert violations[0]["type"] == "invalid_tool"
    assert violations[0]["tool_ref"] == "arbitrary_dangerous_tool"
    assert violations[0]["task_id"] == "t-001"


def test_check_agents_invalid(valid_plan: dict):
    agent_reg = load_agent_registry()
    plan = copy.deepcopy(valid_plan)
    plan["tasks"][1]["assigned_agent"] = "hacker"
    violations = check_agents(plan, agent_reg)
    assert len(violations) == 1
    assert violations[0]["type"] == "unknown_agent"
    assert violations[0]["task_id"] == "t-002"


def test_check_domain_tags_invalid(valid_plan: dict):
    taxonomy = load_taxonomy()
    plan = copy.deepcopy(valid_plan)
    plan["tasks"][0]["domain_tags"] = ["Quantum Computing"]
    violations = check_domain_tags(plan, taxonomy)
    assert len(violations) == 1
    assert violations[0]["type"] == "domain_tag_missing"
    assert violations[0]["domain_ref"] == "Quantum Computing"


def test_check_domain_tags_empty(valid_plan: dict):
    taxonomy = load_taxonomy()
    plan = copy.deepcopy(valid_plan)
    plan["tasks"][0]["domain_tags"] = []
    violations = check_domain_tags(plan, taxonomy)
    assert len(violations) == 1
    assert violations[0]["type"] == "domain_tag_missing"
    assert violations[0]["task_id"] == "t-001"


def test_check_dag_cycle(valid_plan: dict):
    plan = copy.deepcopy(valid_plan)
    # Create cycle: t-001 -> t-002 -> t-001
    plan["dag"]["edges"].append({"from": "t-002", "to": "t-001", "type": "data_dependency"})
    violations = check_dag(plan)
    assert any(v["type"] == "dag_error" and "Cycle detected" in v["description"] for v in violations)


def test_check_dag_task_mismatch(valid_plan: dict):
    plan = copy.deepcopy(valid_plan)
    plan["dag"]["nodes"].append("t-999")
    violations = check_dag(plan)
    assert any(v["type"] == "dag_error" and "t-999" in v["description"] for v in violations)


def test_check_prompt_fidelity_mismatch(valid_plan: dict, frozen_prompt: str):
    plan = copy.deepcopy(valid_plan)
    plan["original_prompt"] = "Something completely altered by an agent."
    violations = check_prompt_fidelity(plan, frozen_prompt)
    assert len(violations) == 1
    assert violations[0]["type"] == "rule_violation"
    assert violations[0]["rule_ref"] == "prompt_fidelity"


def test_check_cognition_placeholder(valid_plan: dict):
    plan = copy.deepcopy(valid_plan)
    plan["cognition"]["risks"] = "N/A"
    violations = check_cognition_substance(plan)
    assert any(v["type"] == "rule_violation" and "placeholder evasion" in v["description"] for v in violations)


def test_check_cognition_too_short(valid_plan: dict):
    plan = copy.deepcopy(valid_plan)
    plan["cognition"]["solution"] = "Short solution."
    violations = check_cognition_substance(plan)
    assert any(v["type"] == "rule_violation" and "too short" in v["description"] for v in violations)


def test_validate_annotated_plan_clean(valid_plan: dict, frozen_prompt: str):
    verdict = validate_annotated_plan(valid_plan, frozen_prompt)
    assert verdict["schema_version"] == "2.0"
    assert verdict["message_type"] == "review_verdict"
    assert verdict["verdict"] == "approved"
    assert verdict["return_to"] is None
    assert len(verdict["violations"]) == 0
    assert "analysis" in verdict["cognition"]


def test_validate_annotated_plan_rejected_tools(valid_plan: dict, frozen_prompt: str):
    plan = copy.deepcopy(valid_plan)
    plan["tasks"][0]["tools_required"].append("nonexistent_tool")
    verdict = validate_annotated_plan(plan, frozen_prompt)
    assert verdict["verdict"] == "rejected_tools"
    assert verdict["return_to"] == "architect"
    assert any(v["type"] == "invalid_tool" for v in verdict["violations"])


def test_validate_annotated_plan_rejected_rules(valid_plan: dict, frozen_prompt: str):
    plan = copy.deepcopy(valid_plan)
    plan["tasks"][0]["domain_tags"] = ["Fake Domain"]
    verdict = validate_annotated_plan(plan, frozen_prompt)
    assert verdict["verdict"] == "rejected_rules"
    assert verdict["return_to"] == "orchestrator"
    assert any(v["type"] == "domain_tag_missing" for v in verdict["violations"])


def test_validate_code_output_clean_bash():
    task = {"task_id": "t-001", "domain_tags": ["Defensive Bash Scripting"]}
    outputs = {
        "sysadmin/hello.sh": (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "trap 'echo \"❌ error\" >&2; exit 1' ERR\n"
            "echo \"Hello\"\n"
            "exit 0\n"
        )
    }
    verdict = validate_code_output(task, outputs)
    assert verdict["verdict"] == "approved"
    assert len(verdict["violations"]) == 0
    assert verdict["critique"] == ""


def test_validate_code_output_missing_pipefail():
    task = {"task_id": "t-001", "domain_tags": ["Defensive Bash Scripting"]}
    outputs = {
        "sysadmin/hello.sh": (
            "#!/usr/bin/env bash\n"
            "trap 'echo \"❌ error\" >&2; exit 1' ERR\n"
            "echo \"Hello\"\n"
            "exit 0\n"
        )
    }
    verdict = validate_code_output(task, outputs)
    assert verdict["verdict"] == "rejected"
    assert any(v["type"] == "missing_pipefail_header" for v in verdict["violations"])
    assert "set -euo pipefail" in verdict["critique"]


def test_validate_code_output_missing_err_trap():
    task = {"task_id": "t-001", "domain_tags": ["Defensive Bash Scripting"]}
    outputs = {
        "sysadmin/hello.sh": (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "echo \"Hello\"\n"
            "exit 0\n"
        )
    }
    verdict = validate_code_output(task, outputs)
    assert verdict["verdict"] == "rejected"
    assert any(v["type"] == "missing_err_trap" for v in verdict["violations"])


def test_validate_code_output_shellcheck_findings():
    task = {"task_id": "t-001", "domain_tags": ["Defensive Bash Scripting"]}
    outputs = {
        "sysadmin/broken.sh": (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "trap 'echo error' ERR\n"
            "if true then echo bad fi\n"
        )
    }
    verdict = validate_code_output(task, outputs)
    assert verdict["verdict"] == "rejected"
    assert any(v["type"] == "shellcheck_findings" for v in verdict["violations"])


def test_validate_code_output_python_syntax():
    task = {"task_id": "t-002", "domain_tags": ["Python Quality"]}
    outputs = {
        "sysadmin/script.py": "def foo(:\n    pass\n"
    }
    verdict = validate_code_output(task, outputs)
    assert verdict["verdict"] == "rejected"
    assert any(v["type"] == "python_syntax_error" for v in verdict["violations"])


def test_validate_code_output_ignore_stdout():
    """Verify execution outputs (stdout, stderr) are not falsely linted as bash scripts."""
    task = {"task_id": "t-002", "domain_tags": ["Defensive Bash Scripting"], "outputs": ["hello_world_result"]}
    outputs = {"stdout": "Hello from Ollama Multi-Agent Pipeline\n"}
    verdict = validate_code_output(task, outputs)
    assert verdict["verdict"] == "approved"
    assert len(verdict["violations"]) == 0

