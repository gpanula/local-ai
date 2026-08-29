"""Unit tests for mcp_core.memory.MemoryStore (Phase 1 data layer).

All tests use a temporary database (``tmp_path``) so they never touch the real
``.localai/memory.db`` runtime store.
"""

import os

import pytest

from mcp_core.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    """A MemoryStore backed by a temp-file database, closed after each test."""
    db_path = os.path.join(str(tmp_path), "memory.db")
    s = MemoryStore(db_path)
    yield s
    s.close()


def _lesson(**overrides):
    base = {
        "category": "sysadmin_bash",
        "keywords": ["trap", "write_file"],
        "rule": "Never nest script content inside subshell strings.",
        "source_task": "sysadmin/prompts/hello_world_test.md",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema creation (idempotent)
# ---------------------------------------------------------------------------
def test_schema_creation_is_idempotent(tmp_path):
    db_path = os.path.join(str(tmp_path), "memory.db")
    MemoryStore(db_path).close()
    # Opening a second time must not error.
    MemoryStore(db_path).close()


def test_schema_creates_expected_tables(tmp_path):
    db_path = os.path.join(str(tmp_path), "memory.db")
    with MemoryStore(db_path) as m:
        tables = {
            r[0]
            for r in m.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','virtual table')"
            )
        }
    assert {"lessons", "pending_lessons", "lessons_fts"} <= tables


# ---------------------------------------------------------------------------
# Full CRUD lifecycle
# ---------------------------------------------------------------------------
def test_insert_and_get_lesson(store):
    lid = store.insert_lesson(_lesson())
    got = store.get_lesson(lid)
    assert got is not None
    assert got["id"] == lid
    assert got["rule"] == "Never nest script content inside subshell strings."
    assert got["keywords"] == ["trap", "write_file"]
    assert got["category"] == "sysadmin_bash"


def test_insert_generates_unique_ids(store):
    id1 = store.insert_lesson(_lesson())
    id2 = store.insert_lesson(_lesson())
    assert id1 != id2
    assert id1.startswith("lesson-")
    assert id2.startswith("lesson-")


def test_get_missing_lesson_returns_none(store):
    assert store.get_lesson("lesson-does-not-exist") is None


def test_list_lessons_all_and_filtered(store):
    store.insert_lesson(_lesson(category="sysadmin_bash"))
    store.insert_lesson(_lesson(category="ansible", keywords=["become"]))
    assert len(store.list_lessons()) == 2
    bash = store.list_lessons(category="sysadmin_bash")
    assert len(bash) == 1
    assert bash[0]["category"] == "sysadmin_bash"
    assert store.list_lessons(category="docker") == []


def test_update_lesson_rule(store):
    lid = store.insert_lesson(_lesson())
    store.update_lesson(lid, {"rule": "UPDATED rule text"})
    assert store.get_lesson(lid)["rule"] == "UPDATED rule text"


def test_update_lesson_keywords(store):
    lid = store.insert_lesson(_lesson())
    store.update_lesson(lid, {"keywords": ["heredoc", "EOF"]})
    assert store.get_lesson(lid)["keywords"] == ["heredoc", "EOF"]


def test_delete_lesson(store):
    lid = store.insert_lesson(_lesson())
    store.delete_lesson(lid)
    assert store.get_lesson(lid) is None


# ---------------------------------------------------------------------------
# FTS5 search
# ---------------------------------------------------------------------------
def test_search_ranks_relevant_lesson_first(store):
    store.insert_lesson(
        _lesson(keywords=["heredoc", "EOF"], rule="Heredoc delimiters at column 0.")
    )
    store.insert_lesson(
        _lesson(keywords=["trap"], rule="Use an ERR trap with set -euo pipefail.")
    )
    results = store.search_lessons("heredoc EOF")
    assert results, "expected at least one result"
    assert results[0]["keywords"] == ["heredoc", "EOF"]


def test_search_no_match_returns_empty(store):
    store.insert_lesson(_lesson())
    assert store.search_lessons("zzzznomatch") == []


def test_search_empty_query_returns_empty(store):
    store.insert_lesson(_lesson())
    assert store.search_lessons("") == []
    assert store.search_lessons("   ") == []


def test_search_top_k_limits_results(store):
    for i in range(5):
        store.insert_lesson(_lesson(keywords=["bash"], rule=f"bash lesson {i}"))
    results = store.search_lessons("bash", top_k=2)
    assert len(results) == 2


def test_search_excludes_deleted_lessons(store):
    lid = store.insert_lesson(_lesson(keywords=["heredoc"], rule="Heredoc rule."))
    store.insert_lesson(_lesson(keywords=["trap"], rule="Trap rule."))
    store.delete_lesson(lid)
    results = store.search_lessons("heredoc")
    assert all(r["id"] != lid for r in results)


def test_search_results_include_rank_field(store):
    store.insert_lesson(_lesson(keywords=["bash"], rule="bash rule."))
    results = store.search_lessons("bash")
    assert results
    assert "rank" in results[0]


# ---------------------------------------------------------------------------
# Pending lessons table
# ---------------------------------------------------------------------------
def test_pending_lesson_insert_and_get(store):
    store.conn.execute(
        """
        INSERT INTO pending_lessons
            (id, staged_at, task_file, proposed_rule, category, keywords,
             reviewer_critique, lesson_type, outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pending-20260828-01",
            "2026-08-28T00:00:00+00:00",
            "sysadmin/prompts/hello_world_test.md",
            "Proposed rule text.",
            "sysadmin_bash",
            '["trap", "write_file"]',
            "Reviewer critique.",
            "solved_pattern",
            "approved",
        ),
    )
    store.conn.commit()
    row = store.conn.execute(
        "SELECT * FROM pending_lessons WHERE id = ?", ("pending-20260828-01",)
    ).fetchone()
    assert row is not None
    assert row["proposed_rule"] == "Proposed rule text."
    assert row["category"] == "sysadmin_bash"


# ---------------------------------------------------------------------------
# Context manager protocol
# ---------------------------------------------------------------------------
def test_context_manager_commits_on_exit(tmp_path):
    db_path = os.path.join(str(tmp_path), "memory.db")
    with MemoryStore(db_path) as m:
        m.insert_lesson(_lesson())
    # Reopen and confirm the insert persisted.
    with MemoryStore(db_path) as m2:
        assert len(m2.list_lessons()) == 1


def test_context_manager_rolls_back_on_exception(tmp_path):
    db_path = os.path.join(str(tmp_path), "memory.db")
    with pytest.raises(RuntimeError):
        with MemoryStore(db_path) as m:
            # Raw uncommitted insert (insert_lesson commits eagerly, so use the
            # connection directly to exercise the rollback path).
            m.conn.execute(
                """
                INSERT INTO lessons
                    (id, category, keywords, rule, created, source_task, lesson_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "lesson-rollback-01",
                    "sysadmin_bash",
                    '["trap"]',
                    "Uncommitted rule.",
                    "2026-08-28",
                    "sysadmin/prompts/hello_world_test.md",
                    "solved_pattern",
                ),
            )
            raise RuntimeError("boom")
    with MemoryStore(db_path) as m2:
        assert m2.list_lessons() == []


# ---------------------------------------------------------------------------
# Vector & hybrid search (Phase 4.03)
# ---------------------------------------------------------------------------
def _embed_lesson(store, lesson_id, rule, keywords, embedding):
    store.insert_lesson(
        {
            "id": lesson_id,
            "rule": rule,
            "keywords": keywords,
            "category": "sysadmin_bash",
            "embeddings": embedding,
        }
    )


def test_vector_search_returns_most_similar_first(store):
    _embed_lesson(store, "v1", "heredoc delimiters", ["heredoc"], [1.0, 0.0, 0.0])
    _embed_lesson(store, "v2", "ansible temp dir", ["ansible"], [0.0, 1.0, 0.0])
    _embed_lesson(store, "v3", "venv isolation", ["venv"], [0.0, 0.0, 1.0])
    results = store.search_lessons_vector([1.0, 0.0, 0.0], top_k=2)
    assert results[0]["id"] == "v1"
    assert results[0]["vector_rank"] > results[1]["vector_rank"]


def test_vector_search_skips_lessons_without_embedding(store):
    store.insert_lesson(_lesson(id="no-embed", rule="No embedding here"))
    _embed_lesson(store, "v1", "heredoc", ["heredoc"], [1.0, 0.0])
    results = store.search_lessons_vector([1.0, 0.0], top_k=5)
    ids = [r["id"] for r in results]
    assert "v1" in ids
    assert "no-embed" not in ids


def test_hybrid_search_combines_signals(store):
    # l1 matches both keyword "heredoc" and vector [1,0,0].
    _embed_lesson(store, "l1", "heredoc delimiters", ["heredoc"], [1.0, 0.0, 0.0])
    # l2 matches only the vector (no keyword overlap with "heredoc").
    _embed_lesson(store, "l2", "unrelated rule", ["unrelated"], [0.9, 0.1, 0.0])
    results = store.search_lessons_hybrid("heredoc", [1.0, 0.0, 0.0], top_k=2)
    assert results[0]["id"] == "l1"


def test_hybrid_search_degrades_to_fts_without_embedding(store):
    store.insert_lesson(_lesson(id="h1", rule="heredoc delimiters", keywords=["heredoc"]))
    # No query embedding -> falls back to FTS5-only.
    results = store.search_lessons_hybrid("heredoc", [], top_k=3)
    assert any(r["id"] == "h1" for r in results)


def test_embeddings_column_migrated_on_existing_db(tmp_path):
    # Simulate a pre-Phase-4 database without the embeddings column.
    import sqlite3

    db_path = os.path.join(str(tmp_path), "old.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE lessons (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'unknown',
            keywords TEXT NOT NULL DEFAULT '[]',
            rule TEXT NOT NULL,
            created TEXT NOT NULL,
            source_task TEXT NOT NULL DEFAULT '',
            lesson_type TEXT NOT NULL DEFAULT 'solved_pattern',
            retrieval_count INTEGER NOT NULL DEFAULT 0,
            prevented_rework_count INTEGER NOT NULL DEFAULT 0,
            ineffective_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()

    # Opening with MemoryStore should add the embeddings column.
    with MemoryStore(db_path) as m:
        cols = {r[1] for r in m.conn.execute("PRAGMA table_info(lessons)").fetchall()}
        assert "embeddings" in cols
        # And vector search should work after migration.
        m.insert_lesson(_lesson(id="m1", rule="heredoc", embeddings=[1.0, 0.0]))
        results = m.search_lessons_vector([1.0, 0.0], top_k=3)
        assert results[0]["id"] == "m1"
