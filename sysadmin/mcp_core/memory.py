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
import math
import os
import re
import sqlite3
import struct
from datetime import date, datetime, timezone
from typing import Any, Optional

from mcp_core.workspace import WORKSPACE_ROOT

# sqlite-vec is optional: if importable, vector/hybrid search is enabled; otherwise
# search_lessons_hybrid degrades gracefully to FTS5-only search.
try:  # pragma: no cover - depends on optional dependency
    import sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:  # pragma: no cover
    sqlite_vec = None
    _SQLITE_VEC_AVAILABLE = False

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
    ineffective_count INTEGER NOT NULL DEFAULT 0,
    embeddings BLOB
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


def _serialize_embedding(embedding: Any) -> Optional[bytes]:
    """Serialize a list of floats to a little-endian float32 BLOB (sqlite-vec format).

    Returns ``None`` when no embedding is provided.
    """
    if embedding is None:
        return None
    if isinstance(embedding, bytes):
        return embedding
    if not isinstance(embedding, (list, tuple)):
        return None
    floats = [float(v) for v in embedding]
    return struct.pack(f"<{len(floats)}f", *floats)


def _deserialize_embedding(blob: Any) -> Optional[list]:
    """Deserialize a float32 BLOB back into a list of floats."""
    if blob is None:
        return None
    if isinstance(blob, (list, tuple)):
        return [float(v) for v in blob]
    try:
        count = len(blob) // 4
        return list(struct.unpack(f"<{count}f", blob))
    except (struct.error, TypeError):
        return None


def _cosine_similarity(a: list, b: list) -> float:
    """Cosine similarity between two equal-length float vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


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
        """Create all tables if they do not exist (idempotent).

        Loads the optional ``sqlite-vec`` extension when available so vector
        search works, and migrates pre-existing databases by adding the
        ``embeddings`` column if it is missing.
        """
        if _SQLITE_VEC_AVAILABLE:
            try:
                self.conn.enable_load_extension(True)
                sqlite_vec.load(self.conn)
            except Exception:  # noqa: BLE001 - vector search is optional
                pass
        self.conn.executescript(_SCHEMA)
        self._migrate_embeddings_column()
        self.conn.commit()

    def _migrate_embeddings_column(self) -> None:
        """Add the ``embeddings`` BLOB column to ``lessons`` if it is missing."""
        cols = {
            r[1]
            for r in self.conn.execute("PRAGMA table_info(lessons)").fetchall()
        }
        if "embeddings" not in cols:
            self.conn.execute("ALTER TABLE lessons ADD COLUMN embeddings BLOB")

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
        auto-generate one. ``keywords`` may be a list or a JSON string. An
        optional ``embeddings`` value (a list of floats) is stored as a BLOB
        for vector search.
        """
        lesson_id = lesson.get("id") or self._next_lesson_id()
        keywords = lesson.get("keywords", [])
        keywords_json = json.dumps(keywords) if not isinstance(keywords, str) else keywords
        embedding_blob = _serialize_embedding(lesson.get("embeddings"))

        self.conn.execute(
            """
            INSERT INTO lessons
                (id, category, keywords, rule, created, source_task, lesson_type,
                 retrieval_count, prevented_rework_count, ineffective_count, embeddings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                embedding_blob,
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

        # Re-sync FTS index if searchable fields changed. Delete from the FTS
        # index BEFORE updating the content table: for external-content FTS5
        # tables the DELETE reads the current content row, so it must run while
        # the old values are still present. Deleting after the UPDATE can raise
        # "database disk image is malformed" (SQLITE_CORRUPT) when the old and
        # new token sets differ (e.g. a single-keyword lesson being rewritten).
        fts_fields_changed = bool({"rule", "keywords", "category"} & set(fields))
        if fts_fields_changed:
            self.conn.execute(
                "DELETE FROM lessons_fts WHERE rowid = (SELECT rowid FROM lessons WHERE id = ?)",
                (lesson_id,),
            )

        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE lessons SET {assignments} WHERE id = ?",
            (*fields.values(), lesson_id),
        )

        if fts_fields_changed:
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
    # Telemetry counters (Phase 5)
    # ------------------------------------------------------------------
    # Counter columns that may be updated via update_telemetry.
    TELEMETRY_FIELDS = ("retrieval_count", "prevented_rework_count", "ineffective_count")

    def increment_retrieval_count(self, lesson_ids: list) -> None:
        """Batch-increment ``retrieval_count`` for each lesson ID.

        No-op when ``lesson_ids`` is empty. Persists to disk (commits).
        """
        if not lesson_ids:
            return
        for lesson_id in lesson_ids:
            self.conn.execute(
                "UPDATE lessons SET retrieval_count = retrieval_count + 1 WHERE id = ?",
                (lesson_id,),
            )
        self.conn.commit()

    def update_telemetry(self, lesson_id: str, field: str, increment: int = 1) -> None:
        """Increment a telemetry counter column for a lesson.

        ``field`` must be one of ``retrieval_count``, ``prevented_rework_count``,
        or ``ineffective_count``. Unknown fields are ignored.
        """
        if field not in self.TELEMETRY_FIELDS:
            return
        self.conn.execute(
            f"UPDATE lessons SET {field} = {field} + ? WHERE id = ?",
            (increment, lesson_id),
        )
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
        (the FTS5 BM25 score; lower is better) and a ``utility_score`` field
        (BM25 magnitude weighted by the lesson's utility multiplier). Lessons
        retrieved frequently without preventing rework are suppressed below the
        top-K threshold. Empty queries and no-match queries return ``[]``.
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
            (match_expr, top_k * 3),
        ).fetchall()

        results = []
        for row in rows:
            lesson = self._row_to_lesson(row)
            lesson["rank"] = row["rank"]
            lesson["utility_score"] = self._utility_score(lesson)
            results.append(lesson)

        # Sort by utility score descending (higher = more useful), then trim.
        results.sort(key=lambda r: r["utility_score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _utility_score(lesson: dict) -> float:
        """Compute the utility-weighted score for a lesson.

        Multiplier = (prevented + 1) / (retrieved + 2). A brand-new lesson
        (0 retrieved, 0 prevented) gets a neutral 0.5 multiplier. The BM25 rank
        is negative (lower = better), so we negate it and add 1 to keep it
        strictly positive (so ties in BM25 are still broken by the multiplier),
        then multiply by the multiplier. Higher = more useful.
        """
        retrieved = int(lesson.get("retrieval_count", 0))
        prevented = int(lesson.get("prevented_rework_count", 0))
        multiplier = (prevented + 1) / (retrieved + 2)
        rank = float(lesson.get("rank", 0.0))
        return (-rank + 1) * multiplier

    # ------------------------------------------------------------------
    # Vector & hybrid search (sqlite-vec, optional)
    # ------------------------------------------------------------------
    def search_lessons_vector(self, query_embedding: list, top_k: int = 3) -> list:
        """Vector similarity search over lessons using cosine similarity.

        Requires ``sqlite-vec`` to be importable. Returns up to ``top_k`` lesson
        dicts, each including a ``vector_rank`` field (cosine similarity; higher
        is better). Lessons without an embedding are skipped. Returns ``[]`` if
        ``sqlite-vec`` is unavailable or no embeddings are stored.
        """
        if not _SQLITE_VEC_AVAILABLE:
            return []
        if not query_embedding:
            return []

        query_blob = _serialize_embedding(query_embedding)
        if query_blob is None:
            return []

        try:
            rows = self.conn.execute(
                """
                SELECT lessons.*, vec_distance_cosine(lessons.embeddings, ?) AS vec_dist
                FROM lessons
                WHERE lessons.embeddings IS NOT NULL
                ORDER BY vec_dist ASC
                LIMIT ?
                """,
                (query_blob, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            # sqlite-vec not loaded for this connection (e.g. extension load failed).
            return []

        results = []
        for row in rows:
            lesson = self._row_to_lesson(row)
            # vec_distance_cosine returns a distance (0 = identical); convert to similarity.
            lesson["vector_rank"] = 1.0 - float(row["vec_dist"])
            results.append(lesson)
        return results

    def search_lessons_hybrid(self, query_text: str, query_embedding: list, top_k: int = 3) -> list:
        """Combine FTS5 BM25 keyword search with vector similarity.

        When ``sqlite-vec`` is unavailable or no embedding is provided, this
        degrades gracefully to FTS5-only search (``search_lessons``). Otherwise
        it merges both signals: a lesson matching both keyword and vector scores
        outranks one matching only a single signal.
        """
        if not _SQLITE_VEC_AVAILABLE or not query_embedding:
            return self.search_lessons(query_text, top_k=top_k)

        fts_results = self.search_lessons(query_text, top_k=top_k * 3)
        vec_results = self.search_lessons_vector(query_embedding, top_k=top_k * 3)

        # Normalize BM25 rank (lower is better) into a 0..1 score.
        fts_scores: dict = {}
        if fts_results:
            max_rank = max(r.get("rank", 0.0) for r in fts_results) or 1.0
            for r in fts_results:
                # BM25 rank is negative; smaller magnitude = better. Map to 0..1.
                fts_scores[r["id"]] = 1.0 - (abs(r.get("rank", 0.0)) / (abs(max_rank) or 1.0))

        vec_scores: dict = {}
        for r in vec_results:
            vec_scores[r["id"]] = r.get("vector_rank", 0.0)

        all_ids = set(fts_scores) | set(vec_scores)
        combined = []
        for lesson_id in all_ids:
            lesson = self.get_lesson(lesson_id)
            if lesson is None:
                continue
            fts = fts_scores.get(lesson_id, 0.0)
            vec = vec_scores.get(lesson_id, 0.0)
            # Apply the utility suppression factor to the combined score.
            multiplier = (int(lesson.get("prevented_rework_count", 0)) + 1) / (
                int(lesson.get("retrieval_count", 0)) + 2
            )
            combined.append((lesson_id, (fts + vec) * multiplier))

        combined.sort(key=lambda item: item[1], reverse=True)
        top_ids = [lesson_id for lesson_id, _ in combined[:top_k]]

        results = []
        for lesson_id in top_ids:
            lesson = self.get_lesson(lesson_id)
            if lesson:
                lesson["hybrid_rank"] = dict(combined)[lesson_id]
                results.append(lesson)
        return results

    # ------------------------------------------------------------------
    # Pending lesson CRUD (staging queue)
    # ------------------------------------------------------------------
    def _next_pending_id(self) -> str:
        """Generate a deterministic ``pending-YYYYMMDD-NN`` ID with a uniqueness guard."""
        prefix = f"pending-{date.today().strftime('%Y%m%d')}"
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        max_seq = 0
        for (rowid,) in self.conn.execute(
            "SELECT id FROM pending_lessons WHERE id LIKE ?", (f"{prefix}-%",)
        ):
            m = pattern.match(rowid)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
        return f"{prefix}-{max_seq + 1:02d}"

    def stage_pending_lesson(self, lesson: dict) -> str:
        """Insert a lesson into the pending review queue and return its ID.

        ``lesson`` may include an explicit ``id`` or omit it to auto-generate a
        ``pending-YYYYMMDD-NN`` ID. ``keywords`` may be a list or JSON string.
        """
        pending_id = lesson.get("id") or self._next_pending_id()
        keywords = lesson.get("keywords", [])
        keywords_json = json.dumps(keywords) if not isinstance(keywords, str) else keywords

        self.conn.execute(
            """
            INSERT INTO pending_lessons
                (id, staged_at, task_file, proposed_rule, category, keywords,
                 reviewer_critique, lesson_type, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pending_id,
                lesson.get("staged_at", _now_iso()),
                lesson.get("task_file", ""),
                lesson["proposed_rule"],
                lesson.get("category", "unknown"),
                keywords_json,
                lesson.get("reviewer_critique", ""),
                lesson.get("lesson_type", "solved_pattern"),
                lesson.get("outcome", ""),
            ),
        )
        self.conn.commit()
        return pending_id

    def list_pending_lessons(self) -> list:
        """Return all pending lessons, ordered by ``staged_at``."""
        rows = self.conn.execute(
            "SELECT * FROM pending_lessons ORDER BY staged_at, id"
        ).fetchall()
        return [self._row_to_pending(r) for r in rows]

    def get_pending_lesson(self, pending_id: str) -> Optional[dict]:
        """Return a pending lesson dict by ID, or ``None`` if not found."""
        row = self.conn.execute(
            "SELECT * FROM pending_lessons WHERE id = ?", (pending_id,)
        ).fetchone()
        return self._row_to_pending(row) if row else None

    def delete_pending_lesson(self, pending_id: str) -> None:
        """Remove a lesson from the pending queue (does not affect ``lessons``)."""
        self.conn.execute("DELETE FROM pending_lessons WHERE id = ?", (pending_id,))
        self.conn.commit()

    def promote_pending_lesson(self, pending_id: str, edits: Optional[dict] = None) -> Optional[str]:
        """Move a pending lesson into the active ``lessons`` table.

        Maps pending fields to lesson fields (``proposed_rule`` → ``rule``,
        ``task_file`` → ``source_task``), applies optional ``edits`` overrides,
        inserts into ``lessons`` (with FTS sync), then deletes the pending row.

        Returns the new active lesson ID, or ``None`` if the pending row is missing.
        """
        pending = self.get_pending_lesson(pending_id)
        if pending is None:
            return None

        edits = edits or {}
        lesson = {
            "category": edits.get("category", pending.get("category", "unknown")),
            "keywords": edits.get("keywords", pending.get("keywords", [])),
            "rule": edits.get("rule", pending.get("proposed_rule", "")),
            "created": edits.get("created", _today()),
            "source_task": edits.get("source_task", pending.get("task_file", "")),
            "lesson_type": edits.get("lesson_type", pending.get("lesson_type", "solved_pattern")),
        }
        lesson_id = self.insert_lesson(lesson)
        self.delete_pending_lesson(pending_id)
        return lesson_id
