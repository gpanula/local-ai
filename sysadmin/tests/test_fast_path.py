"""Unit and integration tests for Architect Fast-Path (Dynamic Orchestrator Bypass)."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mcp_core.context_store import ContextStore
from pipeline import (
    PipelineState,
    promote_plan_to_annotated,
    run_architect,
    run_reviewer,
    run_security,
)
from validator import validate_annotated_plan


class TestFastPath(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = ContextStore(runs_dir=self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_promote_plan_to_annotated_schema(self):
        plan_msg = {
            "schema_version": "2.0",
            "message_type": "plan",
            "run_id": "run-test-fastpath-001",
            "revision": 0,
            "original_prompt": "Create a defensive bash script to verify code quality tools",
            "goal_summary": "Verify code quality toolchain",
            "workflow_mode": "direct",
            "auditor_hint": "balanced",
            "coder_hint": "defensive_bash",
            "tasks": [
                {
                    "task_id": "t-001",
                    "description": "Create sysadmin/verify_tools.sh with ShellCheck and venv isolation",
                    "domain_tags": ["Defensive Bash Scripting", "Code Quality Toolchain"],
                    "agent_hint": "coder",
                    "tools_required": ["write_file", "run_bash"],
                    "inputs": [],
                    "outputs": ["sysadmin/verify_tools.sh"],
                    "constraints": ["set -euo pipefail", "VENV_DIR isolation"],
                }
            ],
            "cognition": {
                "analysis": "Single script verification task without parallel dependencies or handoffs.",
                "risks": "Unquoted variables causing SC2086/SC2046 in generated bash script.",
                "solution": "Synthesize verify_tools.sh with explicit quotes, traps, and venv binary paths.",
                "verification": "Execute ShellCheck and bash execution in sandbox to confirm clean exit.",
            },
        }

        annotated = promote_plan_to_annotated(plan_msg, architect_model="winter-prime:16gb")

        self.assertEqual(annotated["message_type"], "annotated_plan")
        self.assertEqual(annotated["workflow_mode"], "direct")
        self.assertEqual(len(annotated["tasks"]), 1)
        task = annotated["tasks"][0]
        self.assertEqual(task["task_id"], "t-001")
        self.assertEqual(task["assigned_agent"], "coder")
        self.assertIn("write_file", task["tools_required"])
        self.assertEqual(task["depends_on"], [])
        self.assertEqual(annotated["dag"]["nodes"], ["t-001"])
        self.assertEqual(annotated["dag"]["edges"], [])

        # Validate with deterministic pre-filter
        verdict = validate_annotated_plan(
            annotated,
            frozen_prompt=plan_msg["original_prompt"],
            builder_model="winter-prime:16gb",
        )
        self.assertEqual(verdict["verdict"], "approved", f"Pre-filter failed: {verdict.get('violations')}")

    @patch("pipeline.stage_chat")
    def test_run_architect_direct_mode_bypasses_orchestrator(self, mock_stage_chat):
        state = PipelineState("run-fastpath-002", "Build single verify script")
        plan_content = {
            "schema_version": "2.0",
            "message_type": "plan",
            "run_id": state.run_id,
            "revision": 0,
            "original_prompt": state.original_prompt,
            "goal_summary": "Single verify script",
            "workflow_mode": "direct",
            "auditor_hint": "balanced",
            "coder_hint": "defensive_bash",
            "tasks": [
                {
                    "task_id": "t-001",
                    "description": "Create verify script",
                    "domain_tags": ["Defensive Bash Scripting"],
                    "agent_hint": "coder",
                    "tools_required": ["write_file"],
                    "inputs": [],
                    "outputs": ["sysadmin/verify.sh"],
                    "constraints": ["set -euo pipefail"],
                }
            ],
            "cognition": {
                "analysis": "Linear single script task requires no multi-agent orchestration.",
                "risks": "Missing shellcheck compliance or unquoted variable expansion.",
                "solution": "Directly execute coder synthesis with standard defensive headers.",
                "verification": "Validate output with ShellCheck inspect gate.",
            },
        }
        mock_stage_chat.return_value = f"```json\n{json.dumps(plan_content)}\n```"

        next_phase = run_architect(state, self.store, model="winter-prime:16gb")

        self.assertEqual(next_phase, "reviewer")
        self.assertIn("annotated_plan", state.messages)
        self.assertEqual(state.messages["annotated_plan"]["workflow_mode"], "direct")
        event_types = [e["event"] for e in state.events]
        self.assertIn("orchestrator_bypassed", event_types)

    @patch("pipeline.stage_chat")
    def test_direct_mode_reviewer_rejection_routes_to_architect(self, mock_stage_chat):
        state = PipelineState("run-fastpath-003", "Build single verify script")
        annotated_plan = {
            "schema_version": "2.0",
            "message_type": "annotated_plan",
            "run_id": state.run_id,
            "workflow_mode": "direct",
            "tasks": [{"task_id": "t-001", "description": "Single task", "assigned_agent": "coder", "tools_required": ["write_file"], "domain_tags": ["Defensive Bash Scripting"]}],
            "dag": {"nodes": ["t-001"], "edges": []},
            "cognition": {
                "analysis": "Linear single script task requires no multi-agent orchestration.",
                "risks": "Missing shellcheck compliance or unquoted variable expansion.",
                "solution": "Directly execute coder synthesis with standard defensive headers.",
                "verification": "Validate output with ShellCheck inspect gate.",
            },
        }
        state.messages["annotated_plan"] = annotated_plan

        # LLM Reviewer rejects with default return_to="orchestrator"
        mock_stage_chat.return_value = json.dumps({
            "schema_version": "2.0",
            "verdict": "rejected",
            "return_to": "orchestrator",
            "violations": ["Task description too vague"],
        })

        with patch("pipeline.validate_annotated_plan", return_value={"verdict": "approved"}):
            next_phase = run_reviewer(state, self.store, model="winter-reviewer:8gb")

        # In direct mode, return_to="orchestrator" must be routed back to "architect"
        self.assertEqual(next_phase, "architect")
        self.assertEqual(state.architect_revisions_used, 1)

    @patch("pipeline.stage_chat")
    def test_run_architect_clarification_needed_bailout(self, mock_stage_chat):
        state = PipelineState("run-clarify-001", "Validate negative error detection of failures")
        plan_content = {
            "schema_version": "2.0",
            "message_type": "plan",
            "run_id": state.run_id,
            "revision": 0,
            "original_prompt": state.original_prompt,
            "goal_summary": "Ambiguous negative assertion test",
            "workflow_mode": "clarification_needed",
            "tasks": [],
            "open_questions": [
                "Prompt contains confusing stacked negatives ('validate negative error detection of failures'). Is the test asserting failure or success?"
            ],
            "cognition": {
                "analysis": "Prompt contains contradictory pass/fail polarity.",
                "risks": "Coder will invert assertions and fail runtime.",
                "solution": "Bail out early for human clarification.",
                "verification": "Halt pipeline before spending retry budget.",
            },
        }
        mock_stage_chat.return_value = f"```json\n{json.dumps(plan_content)}\n```"

        next_phase = run_architect(state, self.store, model="winter-prime:16gb")

        self.assertEqual(next_phase, "aborted")
        self.assertEqual(state.status, "clarification_needed")
        self.assertIn("Architect clarification required", state.abort_reason)
        event_types = [e["event"] for e in state.events]
        self.assertIn("architect_clarification_bailout", event_types)


if __name__ == "__main__":
    unittest.main()
