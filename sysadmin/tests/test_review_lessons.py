"""Unit tests for the ``review-lessons`` interactive flow (Phase 3.02/3.03).

All interactive prompts are mocked via ``monkeypatch`` on ``builtins.input``.
The ``MemoryStore`` used by the command is monkeypatched to open a temp-file DB
so the real ``.localai/memory.db`` is never touched.
"""

import argparse
import os

import pytest

from mcp_core.memory import MemoryStore
from mcp_cli.commands import memory as memory_cmd
from mcp_cli.commands.memory import ReviewLessonsCommand


@pytest.fixture
def db_path(tmp_path):
    """A temp-file database path shared by the command and the test."""
    return os.path.join(str(tmp_path), "memory.db")


@pytest.fixture
def cmd(monkeypatch, db_path, tmp_path):
    """A ReviewLessonsCommand wired to a temp DB and a temp lessons.md."""
    lessons_md = os.path.join(str(tmp_path), "lessons.md")
    # Point the command's MemoryStore at the temp DB (fresh connection per call).
    monkeypatch.setattr(memory_cmd, "MemoryStore", lambda: MemoryStore(db_path))
    command = ReviewLessonsCommand()
    args = argparse.Namespace(lessons_md=lessons_md)
    return command, args, db_path, lessons_md


def _pending(**overrides):
    base = {
        "category": "sysadmin_bash",
        "keywords": ["trap", "write_file"],
        "proposed_rule": "Never nest script content inside subshell strings.",
        "reviewer_critique": "Do not wrap commands in write_file string payloads.",
        "task_file": "sysadmin/prompts/hello_world_test.md",
        "lesson_type": "solved_pattern",
        "outcome": "approved",
    }
    base.update(overrides)
    return base


def test_empty_queue_prints_clean_message(cmd, capsys):
    command, args, db_path, _ = cmd
    command.run(args)
    out = capsys.readouterr().out
    assert "✅ No pending lessons to review." in out


def test_keep_promotes_and_appends(cmd, capsys, monkeypatch):
    command, args, db_path, lessons_md = cmd
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson(_pending())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "k")

    command.run(args)

    with MemoryStore(db_path) as store:
        # Pending queue is now empty.
        assert store.list_pending_lessons() == []
        # Active lessons table has the promoted lesson.
        active = store.list_lessons()
        assert len(active) == 1
        assert active[0]["rule"] == "Never nest script content inside subshell strings."
    # lessons.md contains the appended block.
    content = open(lessons_md, encoding="utf-8").read()
    assert "**Rule**: Never nest script content inside subshell strings." in content
    # Summary reflects one keep.
    out = capsys.readouterr().out
    assert "Kept: 1 | Modified: 0 | Discarded: 0 | Skipped: 0" in out


def test_modify_applies_edits_before_promotion(cmd, capsys, monkeypatch):
    command, args, db_path, lessons_md = cmd
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson(_pending())
    # First input() = action 'm'; then rule text; then keywords.
    inputs = iter(["m", "UPDATED rule text", "heredoc, EOF"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    command.run(args)

    with MemoryStore(db_path) as store:
        active = store.list_lessons()
        assert len(active) == 1
        assert active[0]["rule"] == "UPDATED rule text"
        assert active[0]["keywords"] == ["heredoc", "EOF"]
    content = open(lessons_md, encoding="utf-8").read()
    assert "**Rule**: UPDATED rule text" in content
    out = capsys.readouterr().out
    assert "Kept: 0 | Modified: 1 | Discarded: 0 | Skipped: 0" in out


def test_discard_removes_pending_without_affecting_active(cmd, capsys, monkeypatch):
    command, args, db_path, lessons_md = cmd
    with MemoryStore(db_path) as store:
        # Pre-existing active lesson that must survive.
        store.insert_lesson({
            "category": "ansible",
            "keywords": ["become"],
            "rule": "Use become: true for privilege escalation.",
            "source_task": "sysadmin/prompts/ansible_venv.md",
        })
        store.stage_pending_lesson(_pending())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "d")

    command.run(args)

    with MemoryStore(db_path) as store:
        assert store.list_pending_lessons() == []
        # Active lessons unchanged (still 1).
        assert len(store.list_lessons()) == 1
    # lessons.md untouched (no block appended / file not created).
    assert not os.path.exists(lessons_md)
    out = capsys.readouterr().out
    assert "Kept: 0 | Modified: 0 | Discarded: 1 | Skipped: 0" in out


def test_skip_leaves_pending_untouched(cmd, capsys, monkeypatch):
    command, args, db_path, lessons_md = cmd
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson(_pending())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "s")

    command.run(args)

    with MemoryStore(db_path) as store:
        # Pending still present.
        assert len(store.list_pending_lessons()) == 1
        # No active lessons.
        assert store.list_lessons() == []
    # No markdown appended / file not created.
    assert not os.path.exists(lessons_md)
    out = capsys.readouterr().out
    assert "Kept: 0 | Modified: 0 | Discarded: 0 | Skipped: 1" in out


def test_mixed_actions_summary_counts(cmd, capsys, monkeypatch):
    command, args, db_path, lessons_md = cmd
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson(_pending(id="pending-20260829-01"))
        store.stage_pending_lesson(_pending(id="pending-20260829-02"))
        store.stage_pending_lesson(_pending(id="pending-20260829-03"))
        store.stage_pending_lesson(_pending(id="pending-20260829-04"))
    # Actions: keep, modify, discard, skip.
    inputs = iter(["k", "m", "modified rule", "", "d", "s"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    command.run(args)

    with MemoryStore(db_path) as store:
        # Skip leaves the 4th lesson in the pending queue.
        remaining = store.list_pending_lessons()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "pending-20260829-04"
        assert len(store.list_lessons()) == 2  # kept + modified
    out = capsys.readouterr().out
    assert "Kept: 1 | Modified: 1 | Discarded: 1 | Skipped: 1" in out
