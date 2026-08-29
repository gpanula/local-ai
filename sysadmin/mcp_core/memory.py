"""SQLite-backed memory store for the Local AI lesson-learning system.

Phase 1 data layer: deterministic CRUD + FTS5 keyword search over approved
lessons and a pending-review queue. No Ollama calls, no embeddings — pure
SQLite.

The database lives at ``WORKSPACE_ROOT/.localai/memory.db`` by default (never
committed to Git). Tests may pass an explicit ``db_path`` (e.g. a ``tmp_path``
file or ``:memory:``) to avoid side effects on the real store.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Optional

from mcp_core.workspace import WORKSPACE_ROOT

# Default runtime database location (git-ignored via .gitignore `.localai/`).
DEFAULT_DB_PATH = os.path.join(WORKSPACE_ROOT, ".localai", "memory.db")

# Columns for the active lessons table.
LESSON_COLUMNS = (
    "id",
    "category",
    "keywords",
    "rule",
    "created",
    "source_task",
    "lesson_type",
    "retrieval_count",
    "prevented_rework_count",
    "ineffective_count",
)

# Columns for the pending review queue.
PENDING_COLUMNS = (
    "id",
    "staged_at",
    "task_file",
    "proposed_rule",
    "category",
    "keywords",
    "reviewer_critique",
    "lesson_type",
    "outcome",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
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
);

CREATE TABLE IF NOT EXISTS pending_lessons (
    id TEXT PRIMARY KEY,
    staged_at TEXT NOT NULL,
    task_file TEXT NOT NULL DEFAULT '',
    proposed_rule TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'unknown',
    keywords TEXT NOT NULL DEFAULT '[]',
    reviewer_critique TEXT NOT NULL DEFAULT '',
    lesson_type TEXT NOT NULL DEFAULT 'solved_pattern',
    outcome TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
    rule,
    keywords,
    category,
    content='lessons',
    content_rowid='rowid'
);
"""


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _today() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def _flatten_keywords(keywords: Any) -> str:
    """Normalize a keywords value (list or JSON string) to a space-joined string."""
    if isinstance(keywords, str):
        try:
            parsed = json.loads(keywords)
            if isinstance(parsed, list):
                keywords = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if isinstance(keywords, (list, tuple)):
        return " ".join(str(k) for k in keywords)
    return str(keywords or "")


class MemoryStore:
    """SQLite-backed store for lessons and the pending review queue.

    Usage::

        with MemoryStore() as m:
            lesson_id = m.insert_lesson({...})
            lesson = m.get_lesson(lesson_id)

    The context manager commits on clean exit and rolls back on exception.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        if self.db_path != ":memory:":
            parent = os.path.dirname(self.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    def _create_schema(self) -> None:
        """Create all tables if they do not exist (idempotent)."""
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        """Commit any pending transaction and close the connection."""
        if self.conn is not None:
            try:
                self.conn.commit()
            finally:
                self.conn.close()
                self.conn = None  # type: ignore[assignment]

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.close()

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_lesson(row: sqlite3.Row) -> dict:
        """Convert a lessons row to a dict, decoding the keywords JSON list."""
        data = dict(row)
        try:
            data["keywords"] = json.loads(data["keywords"])
        except (json.JSONDecodeError, TypeError):
            data["keywords"] = []
        return data

    @staticmethod
    def _row_to_pending(row: sqlite3.Row) -> dict:
        """Convert a pending_lessons row to a dict, decoding keywords JSON."""
        data = dict(row)
        try:
            data["keywords"] = json.loads(data["keywords"])
        except (json.JSONDecodeError, TypeError):
            data["keywords"] = []
        return data

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------
    def _next_lesson_id(self) -> str:
        """Generate a deterministic ``lesson-YYYYMMDD-NN`` ID with a uniqueness guard."""
        prefix = f"lesson-{date.today().strftime('%Y%m%d')}"
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        max_seq = 0
        for (rowid,) in self.conn.execute(
            "SELECT id FROM lessons WHERE id LIKE ?", (f"{prefix}-%",)
        ):
            m = pattern.match(rowid)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
        return f"{prefix}-{max_seq + 1:02d}"

    # ------------------------------------------------------------------
    # Lesson CRUD
    # ------------------------------------------------------------------
    def insert_lesson(self, lesson: dict) -> str:
        """Insert a lesson and return its generated ID.

        ``lesson`` may include an explicit ``id`` (used as-is) or omit it to
        auto-generate one. ``keywords`` may be a list or a JSON string.
        """
        lesson_id = lesson.get("id") or self._next_lesson_id()
        keywords = lesson.get("keywords", [])
        keywords_json = json.dumps(keywords) if not isinstance(keywords, str) else keywords

        self.conn.execute(
            """
            INSERT INTO lessons
                (id, category, keywords, rule, created, source_task, lesson_type,
                 retrieval_count, prevented_rework_count, ineffective_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lesson_id,
                lesson.get("category", "unknown"),
                keywords_json,
                lesson["rule"],
                lesson.get("created", _today()),
                lesson.get("source_task", ""),
                lesson.get("lesson_type", "solved_pattern"),
                int(lesson.get("retrieval_count", 0)),
                int(lesson.get("prevented_rework_count", 0)),
                int(lesson.get("ineffective_count", 0)),
            ),
        )
        self._sync_fts_insert(lesson_id, lesson["rule"], keywords, lesson.get("category", "unknown"))
        self.conn.commit()
        return lesson_id

    def get_lesson(self, lesson_id: str) -> Optional[dict]:
        """Return a lesson dict by ID, or ``None`` if not found."""
        row = self.conn.execute(
            "SELECT * FROM lessons WHERE id = ?", (lesson_id,)
        ).fetchone()
        return self._row_to_lesson(row) if row else None

    def list_lessons(self, category: Optional[str] = None) -> list:
        """Return all lessons, optionally filtered by category (ordered by created)."""
        if category is None:
            rows = self.conn.execute(
                "SELECT * FROM lessons ORDER BY created, id"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM lessons WHERE category = ? ORDER BY created, id",
                (category,),
            ).fetchall()
        return [self._row_to_lesson(r) for r in rows]

    def update_lesson(self, lesson_id: str, updates: dict) -> None:
        """Apply partial updates to a lesson by ID.

        ``updates`` may contain any of the lesson columns. ``keywords`` may be
        a list or JSON string. The FTS index is re-synced when ``rule``,
        ``keywords``, or ``category`` change.
        """
        if not updates:
            return
        allowed = set(LESSON_COLUMNS) - {"id"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return

        if "keywords" in fields:
            kw = fields["keywords"]
            fields["keywords"] = json.dumps(kw) if not isinstance(kw, str) else kw

        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE lessons SET {assignments} WHERE id = ?",
            (*fields.values(), lesson_id),
        )

        # Re-sync FTS index if searchable fields changed.
        if {"rule", "keywords", "category"} & set(fields):
            self.conn.execute(
                "DELETE FROM lessons_fts WHERE rowid = (SELECT rowid FROM lessons WHERE id = ?)",
                (lesson_id,),
            )
            row = self.conn.execute(
                "SELECT rule, keywords, category FROM lessons WHERE id = ?", (lesson_id,)
            ).fetchone()
            if row:
                self._sync_fts_insert(
                    lesson_id, row["rule"], row["keywords"], row["category"]
                )
        self.conn.commit()

    def delete_lesson(self, lesson_id: str) -> None:
        """Delete a lesson by ID and remove it from the FTS index."""
        self.conn.execute(
            "DELETE FROM lessons_fts WHERE rowid = (SELECT rowid FROM lessons WHERE id = ?)",
            (lesson_id,),
        )
        self.conn.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # FTS5 sync helpers
    # ------------------------------------------------------------------
    def _sync_fts_insert(self, lesson_id: str, rule: str, keywords: Any, category: str) -> None:
        """Insert a row into the FTS5 index for the given lesson."""
        self.conn.execute(
            """
            INSERT INTO lessons_fts (rowid, rule, keywords, category)
            SELECT rowid, ?, ?, ? FROM lessons WHERE id = ?
            """,
            (rule, _flatten_keywords(keywords), category, lesson_id),
        )

    # ------------------------------------------------------------------
    # FTS5 keyword search
    # ------------------------------------------------------------------
    def search_lessons(self, query: str, top_k: int = 3) -> list:
        """Full-text keyword search over lessons, ranked by FTS5 BM25.

        Returns up to ``top_k`` lesson dicts, each including a ``rank`` field
        (the FTS5 BM25 score; lower is better). Empty queries and no-match
        queries return ``[]``.
        """
        query = (query or "").strip()
        if not query:
            return []

        # Escape FTS5 special characters so user input is treated literally.
        escaped = re.sub(r'(["\':^*-])', r" \1 ", query)
        match_expr = f'"{escaped}"'

        rows = self.conn.execute(
            """
            SELECT lessons.*, bm25(lessons_fts) AS rank
            FROM lessons_fts
            JOIN lessons ON lessons.rowid = lessons_fts.rowid
            WHERE lessons_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match_expr, top_k),
        ).fetchall()

        results = []
        for row in rows:
            lesson = self._row_to_lesson(row)
            lesson["rank"] = row["rank"]
            results.append(lesson)
        return results
