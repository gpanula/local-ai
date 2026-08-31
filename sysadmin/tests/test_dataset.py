"""Unit tests for dataset export utilities (DPO & SFT)."""

import json
import os
import pytest

from mcp_core.dataset import (
    export_datasets,
    export_dpo_records,
    export_sft_direct_records,
    export_sft_multiturn_records,
    load_trajectories,
    resolve_trajectory_code,
)
from mcp_cli.base import COMMAND_REGISTRY
from mcp_cli.cli import build_parser


def _sample_inline_trajectory(outcome="approved", id="traj-001"):
    return {
        "id": id,
        "timestamp": "2026-08-30T12:00:00Z",
        "task_file": "sysadmin/prompts/hello.md",
        "injected_lessons": ["Always use set -euo pipefail", "Use EXIT trap"],
        "reviewer_critique": "SC2086 unquoted variable expansion on line 12",
        "iterations": 2,
        "outcome": outcome,
        "payload_type": "inline",
        "rejected": "#!/bin/bash\necho $foo\n",
        "chosen": "#!/bin/bash\nset -euo pipefail\necho \"$foo\"\n",
        "diff": None,
        "focused_snippet": None,
        "raw_dir": None,
    }


def _sample_raw_trajectory(tmp_path, outcome="approved", id="traj-002"):
    raw_subdir = tmp_path / "raw" / id
    raw_subdir.mkdir(parents=True, exist_ok=True)
    (raw_subdir / "rejected.sh").write_text("#!/bin/bash\nls $dir\n", encoding="utf-8")
    (raw_subdir / "chosen.sh").write_text("#!/bin/bash\nset -euo pipefail\nls \"$dir\"\n", encoding="utf-8")

    return {
        "id": id,
        "timestamp": "2026-08-30T12:00:00Z",
        "task_file": "sysadmin/prompts/ls.md",
        "injected_lessons": [],
        "reviewer_critique": "SC2086 unquoted variable",
        "iterations": 2,
        "outcome": outcome,
        "payload_type": "diff_and_ref",
        "rejected": "",
        "chosen": "",
        "diff": "--- rejected\n+++ chosen",
        "focused_snippet": "ls \"$dir\"",
        "raw_dir": str(raw_subdir),
    }


def test_resolve_trajectory_code_inline():
    rec = _sample_inline_trajectory()
    rej, cho = resolve_trajectory_code(rec)
    assert "echo $foo" in rej
    assert 'echo "$foo"' in cho


def test_resolve_trajectory_code_from_raw_dir(tmp_path):
    rec = _sample_raw_trajectory(tmp_path)
    rej, cho = resolve_trajectory_code(rec)
    assert "ls $dir" in rej
    assert 'ls "$dir"' in cho


def test_export_dpo_records():
    records = [_sample_inline_trajectory(), _sample_inline_trajectory(outcome="failed", id="traj-fail")]
    dpo_approved = export_dpo_records(records, approved_only=True)
    assert len(dpo_approved) == 1
    item = dpo_approved[0]
    assert item["id"] == "traj-001"
    assert "Always use set -euo pipefail" in item["prompt"]
    assert 'echo "$foo"' in item["chosen"]
    assert "echo $foo" in item["rejected"]

    dpo_all = export_dpo_records(records, approved_only=False)
    assert len(dpo_all) == 2


def test_export_sft_multiturn_records():
    records = [_sample_inline_trajectory()]
    sft_items = export_sft_multiturn_records(records, approved_only=True)
    assert len(sft_items) == 1
    messages = sft_items[0]["messages"]
    assert len(messages) == 5
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert messages[3]["role"] == "user"
    assert "SC2086" in messages[3]["content"]
    assert messages[4]["role"] == "assistant"
    assert 'echo "$foo"' in messages[4]["content"]


def test_export_sft_direct_records():
    records = [_sample_inline_trajectory()]
    sft_items = export_sft_direct_records(records, approved_only=True)
    assert len(sft_items) == 1
    messages = sft_items[0]["messages"]
    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert 'echo "$foo"' in messages[2]["content"]


def test_export_datasets_end_to_end(tmp_path):
    jsonl_path = tmp_path / "trajectories.jsonl"
    out_dir = tmp_path / "training"
    recs = [
        _sample_inline_trajectory(id="t1"),
        _sample_raw_trajectory(tmp_path, id="t2"),
    ]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")

    counts = export_datasets(
        trajectories_path=str(jsonl_path),
        output_dir=str(out_dir),
        formats=["dpo", "sft_multiturn", "sft_direct"],
        approved_only=True,
    )
    assert counts["dpo"] == 2
    assert counts["sft_multiturn"] == 2
    assert counts["sft_direct"] == 2

    assert os.path.exists(out_dir / "dpo_dataset.jsonl")
    assert os.path.exists(out_dir / "sft_multiturn_dataset.jsonl")
    assert os.path.exists(out_dir / "sft_direct_dataset.jsonl")


def test_export_dataset_cli(tmp_path, capsys):
    jsonl_path = tmp_path / "trajectories.jsonl"
    out_dir = tmp_path / "training"
    recs = [_sample_inline_trajectory(id="t1")]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")

    parser = build_parser()
    args = parser.parse_args([
        "export-dataset",
        "--input", str(jsonl_path),
        "--output-dir", str(out_dir),
    ])
    COMMAND_REGISTRY["export-dataset"].run(args)

    out = capsys.readouterr().out
    assert "Successfully exported 3 training sample(s)" in out
