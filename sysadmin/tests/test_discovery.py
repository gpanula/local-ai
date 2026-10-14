"""Unit tests for pipeline_tui.discovery."""

import json
import os
import shutil
import tempfile
import pytest

from pipeline_tui.discovery import find_run, list_runs, load_events_for_run


@pytest.fixture
def mock_trajectories():
    tmp = tempfile.mkdtemp(prefix="test_discovery_")
    traj_path = os.path.join(tmp, "trajectories.jsonl")
    runs_dir = os.path.join(tmp, "runs")
    os.makedirs(runs_dir, exist_ok=True)

    records = [
        {
            "id": "traj-20260907-184346-12e040",
            "timestamp": "2026-09-07T18:43:46+00:00",
            "task_file": "sysadmin/prompts/backup.md",
            "prompt": "Deploy a defensive backup script",
            "author_model": "winter-prime:latest",
            "outcome": "approved",
            "iterations": 1,
            "roles": {"coder": {"strategy": "Use rsync", "risks": "Disk full"}},
            "chosen": "#!/usr/bin/env bash\necho backup",
        },
        {
            "id": "traj-20260907-184352-61ed1a",
            "timestamp": "2026-09-07T18:43:52+00:00",
            "task_file": "sysadmin/prompts/filter.md",
            "prompt": "Test pre-filter routing",
            "author_model": "winter-coder:8gb-trained",
            "outcome": "approved",
            "iterations": 2,
            "roles": {"coder": {"strategy": "Use iptables", "risks": "Drop rule order"}},
            "chosen": "#!/usr/bin/env bash\necho filter",
        },
    ]
    with open(traj_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    yield traj_path, runs_dir
    shutil.rmtree(tmp, ignore_errors=True)


def test_list_runs(mock_trajectories):
    traj_path, runs_dir = mock_trajectories
    runs = list_runs(trajectories_path=traj_path, runs_dir=runs_dir)
    assert len(runs) == 2
    # Newest first
    assert runs[0]["id"] == "traj-20260907-184352-61ed1a"
    assert runs[1]["id"] == "traj-20260907-184346-12e040"


def test_find_run_latest(mock_trajectories):
    traj_path, runs_dir = mock_trajectories
    run = find_run("latest", trajectories_path=traj_path, runs_dir=runs_dir)
    assert run is not None
    assert run["id"] == "traj-20260907-184352-61ed1a"


def test_find_run_exact_id(mock_trajectories):
    traj_path, runs_dir = mock_trajectories
    run = find_run("traj-20260907-184346-12e040", trajectories_path=traj_path, runs_dir=runs_dir)
    assert run is not None
    assert run["id"] == "traj-20260907-184346-12e040"


def test_find_run_prefix(mock_trajectories):
    traj_path, runs_dir = mock_trajectories
    run = find_run("184346", trajectories_path=traj_path, runs_dir=runs_dir)
    assert run is not None
    assert run["id"] == "traj-20260907-184346-12e040"


def test_find_run_keyword(mock_trajectories):
    traj_path, runs_dir = mock_trajectories
    run = find_run("backup", trajectories_path=traj_path, runs_dir=runs_dir)
    assert run is not None
    assert run["id"] == "traj-20260907-184346-12e040"


def test_load_events_for_trajectory_run(mock_trajectories):
    traj_path, runs_dir = mock_trajectories
    run = find_run("backup", trajectories_path=traj_path, runs_dir=runs_dir)
    assert run is not None
    events = load_events_for_run(run)
    assert len(events) >= 6
    types = [e["type"] for e in events]
    assert "pipeline_start" in types
    assert "context_window" in types
    assert "thinking_chunk" in types
    assert "code_synthesized" in types
    assert "linter_result" in types
    assert "review_result" in types
    assert "pipeline_end" in types


def test_list_runs_event_stream_failed_outcome(tmp_path):
    """Verify runs with exit errors or stale streams are reported as failed rather than in_progress."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    ef = runs_dir / "run-failed-001.jsonl"
    events = [
        {"type": "pipeline_start", "timestamp": "2026-09-07T12:00:00Z", "data": {"prompt": "Test failing run"}},
        {"type": "terminal_chunk", "data": {"text": "Exit Code: 1 (indicating an error)"}},
        {"type": "pipeline_end", "data": {"outcome": "failed", "abort_reason": "Execution error"}},
    ]
    with open(ef, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    runs = list_runs(trajectories_path=str(tmp_path / "trajectories.jsonl"), runs_dir=str(runs_dir))
    assert len(runs) == 1
    assert runs[0]["id"] == "run-failed-001"
    assert runs[0]["outcome"] == "failed"
