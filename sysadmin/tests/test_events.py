"""Unit tests for EventEmitter in mcp_core.events."""

import json
import os
import shutil
import tempfile
import pytest

from mcp_core.events import EventEmitter, generate_run_id


@pytest.fixture
def temp_runs_dir():
    tmp = tempfile.mkdtemp(prefix="test_runs_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_generate_run_id():
    rid = generate_run_id()
    assert rid.startswith("run-")
    assert len(rid.split("-")) >= 3


def test_event_emitter_lifecycle(temp_runs_dir):
    emitter = EventEmitter(runs_dir=temp_runs_dir)
    assert os.path.exists(temp_runs_dir)

    emitter.pipeline_start(
        task_file="test.md",
        prompt="Do test work",
        tier="8gb",
        models={"author": "coder:7b", "reviewer": "qwen3:8b"},
        max_retries=3,
    )
    emitter.stage_transition("author", iteration=1)
    emitter.context_window(
        iteration=1,
        system_rules="Rule 1\nRule 2",
        tools=[{"name": "write_file"}],
        lessons=[{"id": "l-1", "title": "Avoid bare which"}],
        user_prompt="Do test work",
        rework_feedback="",
        context_limit=8192,
    )
    emitter.thinking_chunk(1, "coder:7b", "Thinking about defensive checks...")
    emitter.reasoning_chunk(1, "coder:7b", {"strategy": "Step 1", "risks": "Risk 1"})
    emitter.code_synthesized(1, "#!/usr/bin/env bash\necho hi", "script.sh")
    emitter.linter_result(1, passed=True, output="No issues found")
    emitter.review_result(1, verdict="APPROVED", critique="Clean", reviewer_model="qwen3:8b")
    emitter.terminal_chunk("Output line 1\nOutput line 2")
    emitter.pipeline_end(outcome="approved", iterations=1, duration_sec=4.2)

    assert os.path.exists(emitter.run_file)
    with open(emitter.run_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 10
    assert lines[0]["type"] == "pipeline_start"
    assert lines[1]["type"] == "stage_transition"
    assert lines[2]["type"] == "context_window"
    assert lines[2]["data"]["token_breakdown"]["total"] > 0
    assert lines[3]["type"] == "thinking_chunk"
    assert lines[4]["type"] == "reasoning_chunk"
    assert lines[5]["type"] == "code_synthesized"
    assert lines[6]["type"] == "linter_result"
    assert lines[7]["type"] == "review_result"
    assert lines[8]["type"] == "terminal_chunk"
    assert lines[9]["type"] == "pipeline_end"


def test_event_emitter_does_not_crash_on_bad_path():
    # An invalid path that cannot be written to
    emitter = EventEmitter(runs_dir="/dev/null/impossible_dir")
    # Should not raise exception
    emitter.emit("test_event", {"foo": "bar"})
