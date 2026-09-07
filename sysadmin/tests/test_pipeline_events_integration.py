"""Integration test: pipeline-run emission to .localai/runs/."""

import json
import os
import shutil
import tempfile
from unittest.mock import patch

from mcp_cli.commands.pipeline import PipelineRunCommand
from mcp_core.events import EventEmitter


def test_pipeline_run_emits_event_stream():
    tmp_runs = tempfile.mkdtemp(prefix="test_pipe_events_")
    try:
        emitter = EventEmitter(runs_dir=tmp_runs)
        cmd = PipelineRunCommand()

        class Args:
            file = "sysadmin/prompts/hello_world_test.md"
            orchestrator = "qwen3:8b"
            author = "winter-coder:8gb-trained"
            reviewer = "qwen3:8b"
            tier = "8gb"
            keep_models = True
            unload_models = False
            no_orchestrate = True
            no_lint = True
            bootstrap = False
            max_retries = 1
            timeout = 30
            dry_run = True

        prompt = "# Task: Hello World Test"

        # Mock transport calls
        mock_author_resp = (
            "### 1. Analysis & Strategy\nTesting pipeline.\n\n"
            "```bash\n#!/usr/bin/env bash\necho 'hello world'\n```"
        )
        mock_review_resp = "All criteria satisfied.\nDECISION: APPROVED"

        def _fake_mcp(tool_name, arguments):
            if tool_name == "ollama_task_agent":
                return mock_author_resp
            if tool_name == "ollama_chat":
                return mock_review_resp
            return "DEFAULT"

        with patch("mcp_core.transport.call_mcp", side_effect=_fake_mcp):
            res = cmd.revision_loop(prompt, Args(), emitter=emitter)
            assert res["approved"] is True

            # End event
            emitter.pipeline_end(outcome="approved", iterations=1, duration_sec=1.5)

        # Inspect events written
        assert os.path.exists(emitter.run_file)
        with open(emitter.run_file, "r", encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]

        event_types = [e["type"] for e in events]
        assert "stage_transition" in event_types
        assert "context_window" in event_types
        assert "thinking_chunk" in event_types
        assert "code_synthesized" in event_types
        assert "review_result" in event_types
        assert "pipeline_end" in event_types

        # Verify context_window payload
        ctx_evt = next(e for e in events if e["type"] == "context_window")
        assert "token_breakdown" in ctx_evt["data"]
        assert ctx_evt["data"]["user_prompt"] == prompt
    finally:
        shutil.rmtree(tmp_runs, ignore_errors=True)
