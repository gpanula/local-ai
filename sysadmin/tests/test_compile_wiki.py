"""Unit tests for the ``compile-wiki`` command (Phase 7.05)."""

import argparse
import os

import pytest

from mcp_core.memory import MemoryStore
from mcp_cli.commands import memory as memory_cmd
from mcp_cli.commands.memory import CompileWikiCommand


@pytest.fixture
def db_path(tmp_path):
    return os.path.join(str(tmp_path), "memory.db")


@pytest.fixture
def cmd(monkeypatch, db_path, tmp_path):
    """A CompileWikiCommand wired to a temp DB and a temp wiki dir."""
    wiki_dir = os.path.join(str(tmp_path), "wiki")
    monkeypatch.setattr(memory_cmd, "MemoryStore", lambda: MemoryStore(db_path))
    command = CompileWikiCommand()
    args = argparse.Namespace(wiki_dir=wiki_dir)
    return command, args, db_path, wiki_dir


def _lesson(lesson_id, category="bash", keywords=("heredoc",), rule="Rule text."):
    return {
        "id": lesson_id,
        "category": category,
        "keywords": list(keywords),
        "rule": rule,
        "source_task": f"sysadmin/prompts/{lesson_id}.md",
        "created": "2026-08-30",
        "retrieval_count": 0,
        "prevented_rework_count": 0,
        "ineffective_count": 0,
    }


def test_compile_wiki_generates_three_files(cmd, capsys):
    command, args, db_path, wiki_dir = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(_lesson("l1"))
        store.insert_lesson(_lesson("l2", category="ansible", keywords=("become",)))

    command.run(args)

    assert os.path.exists(os.path.join(wiki_dir, "index.md"))
    assert os.path.exists(os.path.join(wiki_dir, "dashboard.md"))
    assert os.path.exists(os.path.join(wiki_dir, "log.md"))
    out = capsys.readouterr().out
    assert "📚 Wiki compiled: index.md (2 lessons), dashboard.md, log.md" in out


def test_compile_wiki_empty_store(cmd, capsys):
    command, args, db_path, wiki_dir = cmd
    command.run(args)
    assert os.path.exists(os.path.join(wiki_dir, "index.md"))
    content = open(os.path.join(wiki_dir, "index.md"), encoding="utf-8").read()
    assert "No lessons recorded." in content
    out = capsys.readouterr().out
    assert "index.md (0 lessons)" in out


def test_compile_wiki_running_twice_is_idempotent(cmd, capsys):
    command, args, db_path, wiki_dir = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson(_lesson("l1"))

    command.run(args)
    command.run(args)

    index = open(os.path.join(wiki_dir, "index.md"), encoding="utf-8").read()
    assert index.count("| [[l1]] |") == 1
    # Log is append-only: two compile events.
    log = open(os.path.join(wiki_dir, "log.md"), encoding="utf-8").read()
    assert log.count("Wiki compiled") == 2
