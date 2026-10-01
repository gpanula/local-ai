"""Unit tests for the ``compact-lessons`` consolidation flow."""

import argparse
import os
import pytest

from mcp_core.memory import MemoryStore
from mcp_cli.commands import memory as memory_cmd
from mcp_cli.commands.memory import CompactLessonsCommand


@pytest.fixture
def db_path(tmp_path):
    return os.path.join(str(tmp_path), "memory.db")


@pytest.fixture
def cmd(monkeypatch, db_path, tmp_path):
    """A CompactLessonsCommand wired to a temporary test DB and temporary lessons.md."""
    lessons_md = os.path.join(str(tmp_path), "lessons.md")
    wiki_dir = os.path.join(str(tmp_path), "wiki")
    monkeypatch.setattr(memory_cmd, "MemoryStore", lambda: MemoryStore(db_path))
    command = CompactLessonsCommand()
    args = argparse.Namespace(
        queue_only=False,
        active_only=False,
        auto=True,
        dry_run=False,
        min_cluster_size=2,
        lessons_md=lessons_md,
        wiki_dir=wiki_dir,
    )
    return command, args, db_path, lessons_md, wiki_dir


def test_compact_empty_store(cmd, capsys):
    command, args, db_path, *_ = cmd
    command.run(args)
    out = capsys.readouterr().out
    assert "Pending Queue: No pending lessons to compact." in out
    assert "Active Lessons: No active lessons to compact." in out


def test_compact_pending_lessons(cmd, capsys):
    command, args, db_path, *_ = cmd
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson({
            "proposed_rule": "Always quote bash variables to avoid word splitting.",
            "category": "Scripting",
            "keywords": ["bash", "env"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "proposed_rule": "Always quote bash variables to avoid word splitting and globbing.",
            "category": "Scripting",
            "keywords": ["bash", "env", "paths"],
        }, deduplicate=False)

    command.run(args)
    out = capsys.readouterr().out
    assert "Compacted 2 pending lessons" in out

    with MemoryStore(db_path) as store:
        pending = store.list_pending_lessons()
        assert len(pending) == 1
        assert "Always quote bash variables to avoid word splitting and globbing." in pending[0]["proposed_rule"]
        assert set(pending[0]["keywords"]) == {"bash", "env", "paths"}


def test_compact_active_lessons(cmd, capsys):
    command, args, db_path, lessons_md, wiki_dir = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "lesson-01",
            "rule": "Always quote bash variables to avoid word splitting.",
            "category": "Testing",
            "keywords": ["pytest", "mock"],
            "retrieval_count": 5,
            "prevented_rework_count": 2,
        })
        store.insert_lesson({
            "id": "lesson-02",
            "rule": "Always quote bash variables to avoid word splitting and globbing.",
            "category": "Testing",
            "keywords": ["pytest", "mock", "fixtures"],
            "retrieval_count": 3,
            "prevented_rework_count": 1,
        })

    command.run(args)
    out = capsys.readouterr().out
    assert "Compacted 2 active lessons" in out
    assert "Wiki re-compiled" in out

    with MemoryStore(db_path) as store:
        lessons = store.list_lessons()
        assert len(lessons) == 1
        assert lessons[0]["rule"] == "Always quote bash variables to avoid word splitting and globbing."
        assert lessons[0]["retrieval_count"] == 8
        assert lessons[0]["prevented_rework_count"] == 3

    assert os.path.exists(lessons_md)
    with open(lessons_md, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Always quote bash variables to avoid word splitting and globbing." in content

    # Assert wiki files were automatically re-compiled
    assert os.path.exists(os.path.join(wiki_dir, "index.md"))
    assert os.path.exists(os.path.join(wiki_dir, "dashboard.md"))
    assert os.path.exists(os.path.join(wiki_dir, "log.md"))


def test_compact_active_invalidates_embeddings(cmd, capsys):
    command, args, db_path, lessons_md, wiki_dir = cmd
    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "lesson-01",
            "rule": "Always quote bash variables to avoid word splitting.",
            "category": "Testing",
            "keywords": ["pytest"],
            "embeddings": [0.1, 0.2, 0.3, 0.4],
        })
        store.insert_lesson({
            "id": "lesson-02",
            "rule": "Always quote bash variables to avoid word splitting and globbing.",
            "category": "Testing",
            "keywords": ["pytest"],
            "embeddings": [0.5, 0.6, 0.7, 0.8],
        })

    command.run(args)
    with MemoryStore(db_path) as store:
        lessons = store.list_lessons()
        assert len(lessons) == 1
        # Check raw database row for embeddings column
        row = store.conn.execute("SELECT embeddings FROM lessons WHERE id = ?", (lessons[0]["id"],)).fetchone()
        assert row["embeddings"] is None


def test_compact_dry_run_reports_sunset_candidates(cmd, capsys):
    command, args, db_path, *_ = cmd
    args.dry_run = True
    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "lesson-bad-01",
            "rule": "Obsolete pattern that fails regularly.",
            "category": "Testing",
            "keywords": ["pytest"],
            "retrieval_count": 2,
            "prevented_rework_count": 0,
            "ineffective_count": 8,
        })

    command.run(args)
    out = capsys.readouterr().out
    assert "Sunset Candidates" in out
    assert "lesson-bad-01" in out
    assert "consistently_ineffective" in out
