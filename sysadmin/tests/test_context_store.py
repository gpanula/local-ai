"""Unit tests for sysadmin.mcp_core.context_store (ContextStore)."""

import hashlib
import json
import os
import pytest

from mcp_core.context_store import ContextStore


@pytest.fixture
def store(tmp_path) -> ContextStore:
    runs_dir = tmp_path / "runs"
    return ContextStore(runs_dir=str(runs_dir))


def test_prompt_hash():
    prompt = "echo 'hello world'"
    expected = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert ContextStore.prompt_hash(prompt) == expected


def test_save_and_load_snapshot(store: ContextStore):
    run_id = "run-001"
    task_id = "t-001"
    snapshot = {
        "schema_version": "1.0",
        "run_id": run_id,
        "task_id": task_id,
        "role": "coder",
        "system_prompt_hash": "abcd1234",
        "tool_registry_version": "2.0",
        "rules_registry_version": "2.0",
        "agent_registry_version": "2.0",
        "injected_lesson_ids": ["l-01"],
        "injected_lesson_count": 1,
        "task_message_ref": f"runs/{run_id}/tasks/{task_id}/task_message.json",
        "context_token_estimate": 500,
        "model_used": "qwen2.5-coder:7b",
    }

    rel_path = store.save_snapshot(run_id, task_id, snapshot)
    assert os.path.exists(os.path.join(store.runs_dir, run_id, "tasks", task_id, "context_snapshot.json"))

    loaded = store.load(rel_path)
    assert loaded == snapshot

    # Also test loading via runs/<run_id>/... path
    alt_ref = f"runs/{run_id}/tasks/{task_id}/context_snapshot.json"
    loaded_alt = store.load(alt_ref)
    assert loaded_alt == snapshot


def test_save_state(store: ContextStore):
    run_id = "run-002"
    state = {
        "run_id": run_id,
        "status": "running",
        "original_prompt": "Run tests",
        "architect_revisions_used": 0,
        "orchestrator_revisions_used": 0,
        "current_phase": "architect",
        "messages": {},
        "tasks": {},
        "events": [],
    }

    rel_path = store.save_state(run_id, state)
    state_file = os.path.join(store.runs_dir, run_id, "state.json")
    assert os.path.isfile(state_file)

    loaded = store.load(rel_path)
    assert loaded["status"] == "running"
    assert loaded["run_id"] == run_id


def test_seal_run_and_cold_load(store: ContextStore):
    run_id = "run-003"
    task_id = "t-002"
    snapshot = {
        "schema_version": "1.0",
        "run_id": run_id,
        "task_id": task_id,
        "role": "sysadmin",
        "model_used": "qwen2.5-coder:7b",
    }
    state = {
        "run_id": run_id,
        "status": "complete",
    }

    snap_rel = store.save_snapshot(run_id, task_id, snapshot)
    state_rel = store.save_state(run_id, state)

    run_dir = os.path.join(store.runs_dir, run_id)
    assert os.path.isdir(run_dir)

    # Seal run
    archive_path = store.seal_run(run_id)
    assert os.path.isfile(archive_path)
    assert archive_path.endswith(f"{run_id}.tar.zst")
    # Hot directory must be deleted
    assert not os.path.exists(run_dir)

    # Transparent cold loading
    loaded_snap = store.load(snap_rel)
    assert loaded_snap == snapshot

    loaded_state = store.load(f"runs/{run_id}/state.json")
    assert loaded_state == state


def test_load_missing_raises(store: ContextStore):
    with pytest.raises(FileNotFoundError):
        store.load("runs/nonexistent-run/nonexistent.json")


def test_seal_missing_run_raises(store: ContextStore):
    with pytest.raises(FileNotFoundError):
        store.seal_run("nonexistent-run")
