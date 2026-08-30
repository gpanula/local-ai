"""Unit tests for the ``audit-lessons`` interactive flow (Phase 6.04).

All interactive prompts are mocked via ``monkeypatch`` on ``builtins.input``.
The ``MemoryStore`` used by the command is monkeypatched to open a temp-file DB
so the real ``.localai/memory.db`` is never touched.
"""

import argparse
import os

import pytest

from mcp_core.memory import MemoryStore
from mcp_cli.commands import memory as memory_cmd
from mcp_cli.commands.memory import AuditLessonsCommand


@pytest.fixture
def db_path(tmp_path):
    return os.path.join(str(tmp_path), "memory.db")


@pytest.fixture
def cmd(monkeypatch, db_path, tmp_path):
    """An AuditLessonsCommand wired to a temp DB, temp rules.md, temp archive."""
    rules_md = os.path.join(str(tmp_path), "SYSTEM_RULES.md")
    archive_md = os.path.join(str(tmp_path), "lessons_archive.md")
    monkeypatch.setattr(memory_cmd, "MemoryStore", lambda: MemoryStore(db_path))
    command = AuditLessonsCommand()
    args = argparse.Namespace(
        rules_md=rules_md,
        archive_md=archive_md,
        min_cluster_size=3,
        min_retrievals=5,
    )
    return command, args, db_path, rules_md, archive_md


def _lesson(lesson_id, keywords, category="sysadmin_bash", **overrides):
    base = {
        "id": lesson_id,
        "keywords": keywords,
        "category": category,
        "rule": f"Rule for {lesson_id}",
        "retrieval_count": 0,
        "prevented_rework_count": 0,
        "ineffective_count": 0,
    }
    base.update(overrides)
    return base


def test_empty_store_prints_clean_message(cmd, capsys):
    command, args, db_path, _, _ = cmd
    command.run(args)
    out = capsys.readouterr().out
    assert "✅ No active lessons to audit." in out


def test_promote_cluster_writes_rule_archives_and_removes(cmd, capsys, monkeypatch):
    command, args, db_path, rules_md, archive_md = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(_lesson("l1", ["heredoc", "EOF", "delimiter"]))
        store.insert_lesson(_lesson("l2", ["heredoc", "EOF"]))
        store.insert_lesson(_lesson("l3", ["heredoc", "delimiter"]))
    # Action 'p' promotes the single cluster.
    monkeypatch.setattr("builtins.input", lambda _prompt="": "p")

    command.run(args)

    # SYSTEM_RULES.md has a promoted rule.
    rules_content = open(rules_md, encoding="utf-8").read()
    assert "### Rule #1" in rules_content
    assert "**Source Lessons**: l1, l2, l3" in rules_content
    # Archive contains the source lessons.
    archive_content = open(archive_md, encoding="utf-8").read()
    assert "id: l1" in archive_content
    assert "id: l2" in archive_content
    assert "id: l3" in archive_content
    # Active lessons removed.
    with MemoryStore(db_path) as store:
        assert store.list_lessons() == []
    out = capsys.readouterr().out
    assert "Promoted: 1" in out


def test_keep_cluster_leaves_lessons_active(cmd, capsys, monkeypatch):
    command, args, db_path, rules_md, archive_md = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(_lesson("l1", ["heredoc", "EOF", "delimiter"]))
        store.insert_lesson(_lesson("l2", ["heredoc", "EOF"]))
        store.insert_lesson(_lesson("l3", ["heredoc", "delimiter"]))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "k")

    command.run(args)

    with MemoryStore(db_path) as store:
        assert len(store.list_lessons()) == 3
    assert not os.path.exists(rules_md)
    assert not os.path.exists(archive_md)
    out = capsys.readouterr().out
    assert "Kept: 1" in out


def test_discard_cluster_removes_lessons(cmd, capsys, monkeypatch):
    command, args, db_path, rules_md, archive_md = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(_lesson("l1", ["heredoc", "EOF", "delimiter"]))
        store.insert_lesson(_lesson("l2", ["heredoc", "EOF"]))
        store.insert_lesson(_lesson("l3", ["heredoc", "delimiter"]))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "d")

    command.run(args)

    with MemoryStore(db_path) as store:
        assert store.list_lessons() == []
    assert not os.path.exists(rules_md)
    out = capsys.readouterr().out
    assert "Discarded: 1" in out


def test_low_utility_delete(cmd, capsys, monkeypatch):
    command, args, db_path, rules_md, archive_md = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(
            _lesson("l1", ["heredoc"], retrieval_count=8, prevented_rework_count=0)
        )
    # No cluster (single lesson), then low-utility action 'd' to delete.
    monkeypatch.setattr("builtins.input", lambda _prompt="": "d")

    command.run(args)

    with MemoryStore(db_path) as store:
        assert store.list_lessons() == []
    out = capsys.readouterr().out
    assert "Deleted: 1" in out


def test_low_utility_rewrite(cmd, capsys, monkeypatch):
    command, args, db_path, rules_md, archive_md = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(
            _lesson("l1", ["heredoc"], retrieval_count=8, prevented_rework_count=0)
        )
    # Low-utility action 'm', then new rule, then new keywords.
    inputs = iter(["m", "NEW RULE TEXT", "heredoc, EOF"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    command.run(args)

    with MemoryStore(db_path) as store:
        lesson = store.get_lesson("l1")
        assert lesson["rule"] == "NEW RULE TEXT"
        assert lesson["keywords"] == ["heredoc", "EOF"]
    out = capsys.readouterr().out
    assert "Rewritten: 1" in out


def test_low_utility_skip(cmd, capsys, monkeypatch):
    command, args, db_path, rules_md, archive_md = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(
            _lesson("l1", ["heredoc"], retrieval_count=8, prevented_rework_count=0)
        )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "s")

    command.run(args)

    with MemoryStore(db_path) as store:
        assert len(store.list_lessons()) == 1
    out = capsys.readouterr().out
    assert "Skipped: 1" in out
