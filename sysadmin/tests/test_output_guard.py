"""Unit tests for Output Boundary Protection in run_dispatch."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mcp_core.context_store import ContextStore
from pipeline import PipelineState, run_dispatch


class TestOutputGuard(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = ContextStore(runs_dir=self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("pipeline.handle_execute_task")
    @patch("pipeline.handle_write_file")
    @patch("pipeline.stage_chat")
    def test_output_guard_blocks_unauthorized_overwrite(self, mock_stage_chat, mock_write_file, mock_exec_task):
        """Test that task t-002 cannot overwrite verified output from t-001 when t-002 has no declared outputs."""
        state = PipelineState("run-guard-001", "Create and test script")
        state.messages["annotated_plan"] = {
            "schema_version": "2.0",
            "message_type": "annotated_plan",
            "tasks": [
                {
                    "task_id": "t-001",
                    "description": "Synthesize script",
                    "assigned_agent": "coder",
                    "tools_required": ["write_file"],
                    "inputs": [],
                    "outputs": ["sysadmin/target.sh"],
                },
                {
                    "task_id": "t-002",
                    "description": "Assert binaries and verify script",
                    "assigned_agent": "coder",
                    "tools_required": ["run_bash"],
                    "inputs": ["sysadmin/target.sh"],
                    "outputs": [],
                },
            ],
        }

        # t-001 outputs valid target.sh
        t1_response = json.dumps({
            "schema_version": "2.0",
            "message_type": "execution_result",
            "task_id": "t-001",
            "role": "coder",
            "status": "success",
            "outputs": {
                "sysadmin/target.sh": "#!/bin/bash\nset -euo pipefail\ntrap 'echo \"❌ [ERROR] Line ${LINENO}\" >&2; exit 1' ERR\necho 'valid t1 content'\nexit 0\n",
            },
        })

        # t-002 erroneously emits an overwrite of target.sh despite outputs: []
        t2_response = json.dumps({
            "schema_version": "2.0",
            "message_type": "execution_result",
            "task_id": "t-002",
            "role": "coder",
            "status": "success",
            "outputs": {
                "sysadmin/target.sh": "#!/bin/bash\nset -euo pipefail\ntrap 'echo \"❌ [ERROR] Line ${LINENO}\" >&2; exit 1' ERR\necho 'corrupted t2 overwrite'\nexit 0\n",
            },
        })

        reviewer_approve = json.dumps({
            "schema_version": "2.0",
            "verdict": "approved",
            "violations": [],
        })
        security_clear = json.dumps({
            "schema_version": "2.0",
            "verdict": "cleared",
            "threats": [],
        })

        def fake_stage_chat(role, system_prompt, user_content, model=None):
            if role == "reviewer":
                return reviewer_approve
            if role == "security":
                return security_clear
            if role == "coder":
                parsed = json.loads(user_content)
                if parsed.get("task_id") == "t-001":
                    return t1_response
                return t2_response
            return "{}"

        mock_stage_chat.side_effect = fake_stage_chat
        mock_write_file.return_value = "Wrote file"
        mock_exec_task.return_value = "- **Exit Code**: `0`\nSuccess"

        phase = run_dispatch(state, self.store, model="winter-prime:latest")

        self.assertEqual(phase, "complete")
        # handle_write_file should ONLY have been called for t-001, NOT for t-002 overwrite!
        mock_write_file.assert_called_once_with(
            "sysadmin/target.sh",
            "#!/bin/bash\nset -euo pipefail\ntrap 'echo \"❌ [ERROR] Line ${LINENO}\" >&2; exit 1' ERR\necho 'valid t1 content'\nexit 0\n",
            make_executable=True,
        )

    @patch("pipeline.handle_execute_task")
    @patch("pipeline.handle_write_file")
    @patch("pipeline.stage_chat")
    def test_output_guard_drops_undeclared_additional_files(self, mock_stage_chat, mock_write_file, mock_exec_task):
        """Test that undeclared files emitted by a task with explicit declared outputs are dropped."""
        state = PipelineState("run-guard-002", "Synthesize single script")
        state.messages["annotated_plan"] = {
            "schema_version": "2.0",
            "message_type": "annotated_plan",
            "tasks": [
                {
                    "task_id": "t-001",
                    "description": "Synthesize script",
                    "assigned_agent": "coder",
                    "tools_required": ["write_file"],
                    "inputs": [],
                    "outputs": ["sysadmin/authorized.sh"],
                },
            ],
        }

        # Coder attempts to output both authorized.sh and rogue.sh
        coder_response = json.dumps({
            "schema_version": "2.0",
            "message_type": "execution_result",
            "task_id": "t-001",
            "role": "coder",
            "status": "success",
            "outputs": {
                "sysadmin/authorized.sh": "#!/bin/bash\nset -euo pipefail\ntrap 'echo \"❌ [ERROR] Line ${LINENO}\" >&2; exit 1' ERR\necho 'authorized'\nexit 0\n",
                "sysadmin/rogue.sh": "#!/bin/bash\nset -euo pipefail\ntrap 'echo \"❌ [ERROR] Line ${LINENO}\" >&2; exit 1' ERR\necho 'rogue'\nexit 0\n",
            },
        })

        reviewer_approve = json.dumps({
            "schema_version": "2.0",
            "verdict": "approved",
            "violations": [],
        })
        security_clear = json.dumps({
            "schema_version": "2.0",
            "verdict": "cleared",
            "threats": [],
        })

        def fake_stage_chat(role, system_prompt, user_content, model=None):
            if role == "reviewer":
                return reviewer_approve
            if role == "security":
                return security_clear
            return coder_response

        mock_stage_chat.side_effect = fake_stage_chat
        mock_write_file.return_value = "Wrote file"
        mock_exec_task.return_value = "- **Exit Code**: `0`\nSuccess"

        phase = run_dispatch(state, self.store, model="winter-prime:latest")

        self.assertEqual(phase, "complete")
        # Only authorized.sh was written
        mock_write_file.assert_called_once_with(
            "sysadmin/authorized.sh",
            "#!/bin/bash\nset -euo pipefail\ntrap 'echo \"❌ [ERROR] Line ${LINENO}\" >&2; exit 1' ERR\necho 'authorized'\nexit 0\n",
            make_executable=True,
        )


if __name__ == "__main__":
    unittest.main()
