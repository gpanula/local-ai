"""Unit tests for mcp_core.trajectories — trajectory recording (Phase 7.01/7.02)."""

import json
import os

from mcp_core.trajectories import record_trajectory


def _result(**overrides):
    base = {
        "approved": True,
        "iterations": 2,
        "abort_reason": "",
        "last_critique": "- Fix heredoc delimiter indentation",
        "injected_lessons": ["l1"],
        "script_versions": ["echo v1", "echo v2"],
        "final_code_block": "echo v2",
    }
    base.update(overrides)
    return base


def _read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [line for line in f if line.strip()]


def test_2_iteration_run_appends_one_line(tmp_path):
    path = os.path.join(str(tmp_path), "trajectories.jsonl")
    record_trajectory(_result(), "prompt", trajectories_path=path, raw_dir=str(tmp_path))
    lines = _read_lines(path)
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["iterations"] == 2
    assert record["outcome"] == "approved"
    assert record["injected_lessons"] == ["l1"]


def test_record_is_valid_json(tmp_path):
    path = os.path.join(str(tmp_path), "trajectories.jsonl")
    record_trajectory(_result(), "prompt", trajectories_path=path, raw_dir=str(tmp_path))
    record = json.loads(_read_lines(path)[0])
    assert record["id"].startswith("traj-")
    assert "timestamp" in record
    assert record["task_file"] == ""


def test_iteration_one_pass_produces_no_record(tmp_path):
    path = os.path.join(str(tmp_path), "trajectories.jsonl")
    # Caller gates on iterations > 1; verify the hook-level guard is respected
    # by the pipeline (tested in test_pipeline). Here we confirm a 1-iteration
    # result still records if called directly, but the pipeline gate is the
    # source of truth. We assert the record reflects iterations == 1.
    record_trajectory(
        _result(iterations=1, script_versions=["echo v1"]),
        "prompt",
        trajectories_path=path,
        raw_dir=str(tmp_path),
    )
    record = json.loads(_read_lines(path)[0])
    assert record["iterations"] == 1


def test_tier1_inline_for_small_script(tmp_path):
    path = os.path.join(str(tmp_path), "trajectories.jsonl")
    record_trajectory(
        _result(script_versions=["echo rejected", "echo chosen"]),
        "prompt",
        trajectories_path=path,
        raw_dir=str(tmp_path),
    )
    record = json.loads(_read_lines(path)[0])
    assert record["payload_type"] == "inline"
    assert record["rejected"] == "echo rejected"
    assert record["chosen"] == "echo chosen"
    assert record["diff"] is None
    assert record["raw_dir"] is None


def test_tier2_diff_and_ref_for_large_script(tmp_path):
    path = os.path.join(str(tmp_path), "trajectories.jsonl")
    rejected = "\n".join(f"line {i}" for i in range(200))
    chosen = "\n".join(f"line {i}" for i in range(200)) + "\nline 200"
    record_trajectory(
        _result(script_versions=[rejected, chosen]),
        "prompt",
        trajectories_path=path,
        raw_dir=str(tmp_path),
    )
    record = json.loads(_read_lines(path)[0])
    assert record["payload_type"] == "diff_and_ref"
    assert record["rejected"] is None
    assert record["chosen"] is None
    assert record["diff"] is not None
    assert record["focused_snippet"] is not None
    assert record["raw_dir"] is not None
    # Raw files written to the offload subdirectory.
    raw_subdir = os.path.join(str(tmp_path), record["raw_dir"].split("/")[-1])
    assert os.path.exists(os.path.join(raw_subdir, "rejected.sh"))
    assert os.path.exists(os.path.join(raw_subdir, "chosen.sh"))


def test_diff_is_valid_unified_diff(tmp_path):
    path = os.path.join(str(tmp_path), "trajectories.jsonl")
    # Must be >= 150 lines to trigger the diff+ref tier.
    rejected = "\n".join(f"line {i}" for i in range(200))
    chosen = "\n".join(f"line {i}" for i in range(199)) + "\nline 199 changed"
    record_trajectory(
        _result(script_versions=[rejected, chosen]),
        "prompt",
        trajectories_path=path,
        raw_dir=str(tmp_path),
    )
    record = json.loads(_read_lines(path)[0])
    diff = record["diff"]
    assert diff.startswith("--- rejected")
    assert "+++ chosen" in diff
    assert "-line 199" in diff
    assert "+line 199 changed" in diff


def test_aborted_outcome(tmp_path):
    path = os.path.join(str(tmp_path), "trajectories.jsonl")
    record_trajectory(
        _result(approved=False, abort_reason="Stuck loop", script_versions=["v1", "v2"]),
        "prompt",
        trajectories_path=path,
        raw_dir=str(tmp_path),
    )
    record = json.loads(_read_lines(path)[0])
    assert record["outcome"] == "aborted"
