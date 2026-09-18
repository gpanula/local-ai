"""Unit and integration tests for VRAM-Aware Coder Dynamic Selection & Model Escalation Cascade."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

from mcp_core.context_store import ContextStore
from mcp_core.hardware import (
    get_default_model,
    get_escalation_model,
    get_primary_coder_model,
    TIER_8GB,
    TIER_16GB,
    TIER_24GB,
)
from pipeline import (
    PipelineState,
    resolve_coder_model,
    resolve_escalation_model,
    run_dispatch,
)


class TestModelEscalation(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = ContextStore(runs_dir=self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_tier_escalation_models_respect_vram(self):
        # Laptop 8GB tier: must NEVER resolve to a 16gb or 24gb model
        model_8gb = get_escalation_model(tier="8gb", role="coder")
        self.assertEqual(model_8gb, "deepseek-r1:8b")
        self.assertNotIn("16gb", model_8gb)
        self.assertNotIn("24gb", model_8gb)

        # 16GB tier
        model_16gb = get_escalation_model(tier="16gb", role="coder")
        self.assertEqual(model_16gb, "deepseek-coder-v2:16b")

        # 24GB tier
        model_24gb = get_escalation_model(tier="24gb", role="coder")
        self.assertEqual(model_24gb, "deepseek-coder-v2:16b")

    def test_resolve_coder_model_precedence(self):
        task = {"assigned_agent": "coder"}
        state = PipelineState("run-esc-001", "Test task")
        state.tier = "8gb"

        # 1. Default for tier
        self.assertEqual(resolve_coder_model(task, state=state, tier="8gb"), "winter-coder:8gb")

        # 2. Task annotation override
        task_with_model = {"assigned_agent": "coder", "coder_model": "custom-coder:latest"}
        self.assertEqual(resolve_coder_model(task_with_model, state=state), "custom-coder:latest")

        # 3. State/CLI override
        state.coder_model = "cli-coder:8gb"
        self.assertEqual(resolve_coder_model(task, state=state), "cli-coder:8gb")

    @patch("pipeline.handle_unload_model")
    @patch("pipeline.stage_chat")
    @patch("pipeline.validate_code_output")
    def test_escalation_cascade_on_repeated_failure(self, mock_linter, mock_chat, mock_unload):
        state = PipelineState("run-esc-002", "Fix tricky bash syntax")
        state.tier = "8gb"
        state.messages["annotated_plan"] = {
            "schema_version": "2.0",
            "message_type": "annotated_plan",
            "tasks": [
                {
                    "task_id": "t-001",
                    "assigned_agent": "coder",
                    "description": "Create tricky script",
                    "tools_required": ["write_file"],
                    "outputs": ["sysadmin/script.sh"],
                }
            ],
        }

        # Attempt 1 & 2: Primary coder fails linter gate
        # Attempt 3: Escalated model passes linter gate and code review
        mock_linter.side_effect = [
            {"verdict": "rejected", "critique": "SC2086 unquoted var", "violations": [{"type": "ShellCheck", "description": "SC2086"}]},
            {"verdict": "rejected", "critique": "SC2086 unquoted var still present", "violations": [{"type": "ShellCheck", "description": "SC2086"}]},
            {"verdict": "approved", "critique": "Passed all defensive standards"},
        ]

        # Return mock JSON outputs for 3 attempts + reviewer + security
        mock_chat.side_effect = [
            # Attempt 1 (coder: winter-coder:8gb)
            json.dumps({"schema_version": "2.0", "status": "success", "outputs": {"sysadmin/script.sh": "echo $VAR"}}),
            # Attempt 2 (coder: winter-coder:8gb)
            json.dumps({"schema_version": "2.0", "status": "success", "outputs": {"sysadmin/script.sh": "echo $VAR"}}),
            # Attempt 3 (escalated: deepseek-r1:8b)
            json.dumps({"schema_version": "2.0", "status": "success", "outputs": {"sysadmin/script.sh": "echo \"$VAR\""}}),
            # Reviewer code gate
            json.dumps({"schema_version": "2.0", "verdict": "approved", "violations": []}),
            # Security code gate
            json.dumps({"schema_version": "2.0", "verdict": "cleared", "threats": []}),
        ]

        with patch("pipeline.handle_write_file", return_value="Written"), \
             patch("pipeline.handle_execute_task", return_value="- **Exit Code**: `0`\nSuccess"):
            phase = run_dispatch(state, self.store, model="winter-coder:8gb", tier="8gb")

        self.assertEqual(phase, "complete")
        self.assertEqual(state.tasks["t-001"]["retries"], 2)

        # Verify models called: attempts 1 & 2 used winter-coder:8gb; attempt 3 used deepseek-r1:8b
        chat_calls = mock_chat.call_args_list
        self.assertEqual(chat_calls[0].kwargs["model"], "winter-coder:8gb")
        self.assertEqual(chat_calls[1].kwargs["model"], "winter-coder:8gb")
        self.assertEqual(chat_calls[2].kwargs["model"], "deepseek-r1:8b")

        # Verify VRAM unload was called for primary model before escalation AND after completion on 8GB tier
        mock_unload.assert_any_call("winter-coder:8gb")
        mock_unload.assert_any_call("deepseek-r1:8b")

        # Verify model_escalated event was emitted
        events = [e["event"] for e in state.events]
        self.assertIn("model_escalated", events)

    @patch("pipeline.stage_chat")
    @patch("pipeline.validate_code_output")
    def test_no_escalation_flag_preserves_strict_retry(self, mock_linter, mock_chat):
        state = PipelineState("run-esc-003", "Strict run")
        state.tier = "8gb"
        state.no_escalation = True
        state.messages["annotated_plan"] = {
            "schema_version": "2.0",
            "message_type": "annotated_plan",
            "tasks": [
                {
                    "task_id": "t-001",
                    "assigned_agent": "coder",
                    "description": "Create strict script",
                    "tools_required": ["write_file"],
                    "outputs": ["sysadmin/strict.sh"],
                }
            ],
        }

        mock_linter.return_value = {
            "verdict": "rejected",
            "critique": "SC2086 unquoted var",
            "violations": [{"type": "ShellCheck", "description": "SC2086"}],
        }
        mock_chat.return_value = json.dumps({
            "schema_version": "2.0",
            "status": "success",
            "outputs": {"sysadmin/strict.sh": "echo $VAR"},
        })

        phase = run_dispatch(state, self.store, model="winter-coder:8gb", tier="8gb")

        self.assertEqual(phase, "aborted")
        self.assertEqual(state.status, "aborted")
        # With no_escalation=True, max retries is 2 (total 3 attempts on primary model, no escalation event)
        self.assertEqual(state.tasks["t-001"]["retries"], 3)
        events = [e["event"] for e in state.events]
        self.assertNotIn("model_escalated", events)


if __name__ == "__main__":
    unittest.main()
