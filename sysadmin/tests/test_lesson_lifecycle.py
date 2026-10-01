"""End-to-end integration tests for the lesson memory lifecycle.

Covers Stage 1: Lexical Dedup Lifecycle:
1. Ingestion deduplication against pending queue.
2. Promotion guard detecting new vs duplicate lessons.
3. Ingestion deduplication against active lessons (incrementing ineffective_count).
4. Promotion reinforcement of active duplicates (incrementing reinforcement_count & retrieval_count).
5. Git-canonical lessons.md integrity (no duplicate rules appended).
6. FTS prompt injection retrieval and formatting.
7. Pending queue compaction consolidating near-duplicate variants.
8. Retirement / sunset decay detection.
"""

from __future__ import annotations

import argparse
from datetime import date
import os
import pytest

from mcp_cli.commands import memory as memory_cmd
from mcp_cli.commands.memory import CompactLessonsCommand
from mcp_core.audit import flag_low_utility
from mcp_core.injection import format_lessons_for_prompt
from mcp_core.lessons_writer import append_lesson_to_markdown
from mcp_core.memory import MemoryStore


def test_lesson_lifecycle_end_to_end(tmp_path):
    db_path = str(tmp_path / "memory.db")
    lessons_md = str(tmp_path / "lessons.md")
    wiki_dir = str(tmp_path / "wiki")

    # -------------------------------------------------------------------------
    # Step 1: Stage Lesson A into pending queue
    # -------------------------------------------------------------------------
    rule_a_v1 = "Always quote bash variables in scripts to avoid word splitting and globbing errors."
    with MemoryStore(db_path) as store:
        staged_id_1 = store.stage_pending_lesson({
            "proposed_rule": rule_a_v1,
            "category": "Defensive Bash Scripting",
            "keywords": ["bash", "quoting", "globbing"],
            "task_file": "sysadmin/prompts/test_task.md",
        })
        assert staged_id_1.startswith("pending-")
        pending = store.list_pending_lessons()
        assert len(pending) == 1
        assert pending[0]["id"] == staged_id_1

    # -------------------------------------------------------------------------
    # Step 2: Stage near-duplicate of Lesson A -> Dedup against pending queue
    # -------------------------------------------------------------------------
    rule_a_v2 = "Always quote bash variables in scripts to avoid word splitting errors."
    with MemoryStore(db_path) as store:
        staged_id_2 = store.stage_pending_lesson({
            "proposed_rule": rule_a_v2,
            "category": "Defensive Bash Scripting",
            "keywords": ["bash", "quoting"],
        })
        assert staged_id_2 == staged_id_1
        pending = store.list_pending_lessons()
        assert len(pending) == 1

    # -------------------------------------------------------------------------
    # Step 3: Promote Lesson A to active table
    # -------------------------------------------------------------------------
    with MemoryStore(db_path) as store:
        promoted_id_1, is_new = store.promote_pending_lesson(staged_id_1)
        assert is_new is True
        assert promoted_id_1.startswith("lesson-")

        # Emulate CLI review-lessons: append to lessons.md only if is_new
        if is_new:
            promoted_lesson = store.get_lesson(promoted_id_1)
            append_lesson_to_markdown(promoted_lesson, lessons_md)

        # Verify database state
        assert len(store.list_pending_lessons()) == 0
        active = store.list_lessons()
        assert len(active) == 1
        assert active[0]["id"] == promoted_id_1
        assert active[0]["reinforcement_count"] == 0
        assert active[0]["ineffective_count"] == 0

    # -------------------------------------------------------------------------
    # Step 4: Ingestion duplicate against active lesson -> increment ineffective_count
    # -------------------------------------------------------------------------
    rule_a_v3 = "Always quote bash variables in scripts to avoid unexpected word splitting and globbing errors."
    with MemoryStore(db_path) as store:
        matched_active_id = store.stage_pending_lesson({
            "proposed_rule": rule_a_v3,
            "category": "Defensive Bash Scripting",
            "keywords": ["bash", "quoting"],
        })
        assert matched_active_id == promoted_id_1
        # Pending queue remains empty
        assert len(store.list_pending_lessons()) == 0
        # Ineffective count is incremented on active lesson
        active_lesson = store.get_lesson(promoted_id_1)
        assert active_lesson["ineffective_count"] == 1
        assert active_lesson["reinforcement_count"] == 0

    # -------------------------------------------------------------------------
    # Step 5: Promotion guard against active duplicate -> reinforcement
    # -------------------------------------------------------------------------
    # Force stage a variant bypass (e.g. legacy or deduplicate=False)
    with MemoryStore(db_path) as store:
        bypassed_id = store.stage_pending_lesson({
            "proposed_rule": "Always quote bash variables in scripts to avoid word splitting errors completely.",
            "category": "Defensive Bash Scripting",
            "keywords": ["bash", "quoting"],
        }, deduplicate=False)
        assert len(store.list_pending_lessons()) == 1

        promoted_id_again, is_new_again = store.promote_pending_lesson(bypassed_id)
        assert promoted_id_again == promoted_id_1
        assert is_new_again is False

        # In review-lessons, only append if is_new is True
        if is_new_again:
            append_lesson_to_markdown(store.get_lesson(promoted_id_again), lessons_md)

        # Active lessons count should STILL be 1 (no duplicate active lesson created)
        assert len(store.list_lessons()) == 1
        assert len(store.list_pending_lessons()) == 0

        reinforced_lesson = store.get_lesson(promoted_id_1)
        assert reinforced_lesson["reinforcement_count"] == 1
        assert reinforced_lesson["retrieval_count"] == 1

    # -------------------------------------------------------------------------
    # Step 6: Verify markdown integrity (single entry for Lesson A)
    # -------------------------------------------------------------------------
    assert os.path.exists(lessons_md)
    with open(lessons_md, "r", encoding="utf-8") as f:
        md_text = f.read()
    # The promoted ID should appear exactly once in frontmatter
    assert md_text.count(f"id: {promoted_id_1}") == 1

    # -------------------------------------------------------------------------
    # Step 7: Prompt injection retrieval and formatting
    # -------------------------------------------------------------------------
    with MemoryStore(db_path) as store:
        retrieved = store.search_lessons("bash")
        assert len(retrieved) >= 1
        assert retrieved[0]["id"] == promoted_id_1

        prompt_block = format_lessons_for_prompt(retrieved)
        assert "Relevant Lessons from Past Runs" in prompt_block
        assert "Always quote bash variables in scripts to avoid word splitting and globbing errors." in prompt_block
        assert "Category: Defensive Bash Scripting" in prompt_block

    # -------------------------------------------------------------------------
    # Step 8: Compaction of pending queue with Lesson B variants
    # -------------------------------------------------------------------------
    rule_b_v1 = "Always isolate python virtual environments in sysadmin scripts before running tools."
    rule_b_v2 = "Always isolate python virtual environments in sysadmin scripts before executing tools."
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson({
            "proposed_rule": rule_b_v1,
            "category": "Binary Isolation",
            "keywords": ["venv", "python", "isolation"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "proposed_rule": rule_b_v2,
            "category": "Binary Isolation",
            "keywords": ["venv", "python", "sysadmin"],
        }, deduplicate=False)
        assert len(store.list_pending_lessons()) == 2

    # Run compact-lessons command
    cmd = CompactLessonsCommand()
    args = argparse.Namespace(
        queue_only=True,
        active_only=False,
        auto=True,
        dry_run=False,
        min_cluster_size=2,
        lessons_md=lessons_md,
        wiki_dir=wiki_dir,
    )
    with patch_memorystore(db_path):
        cmd.run(args)

    with MemoryStore(db_path) as store:
        pending_b = store.list_pending_lessons()
        assert len(pending_b) == 1
        consolidated_b_id = pending_b[0]["id"]
        assert "Always isolate python virtual environments" in pending_b[0]["proposed_rule"]
        assert set(pending_b[0]["keywords"]) == {"venv", "python", "isolation", "sysadmin"}

    # -------------------------------------------------------------------------
    # Step 9: Promote consolidated Lesson B -> Active count = 2
    # -------------------------------------------------------------------------
    with MemoryStore(db_path) as store:
        promoted_b_id, is_new_b = store.promote_pending_lesson(consolidated_b_id)
        assert is_new_b is True
        assert promoted_b_id != promoted_id_1
        assert len(store.list_lessons()) == 2
        assert len(store.list_pending_lessons()) == 0

    # -------------------------------------------------------------------------
    # Step 10: Flag low utility & sunset candidates
    # -------------------------------------------------------------------------
    with MemoryStore(db_path) as store:
        # Lesson A has 1 retrieval and 1 ineffective (ratio 1 / 2 = 0.50, not > 0.50 yet)
        # Update Lesson A to be consistently ineffective
        store.update_lesson(promoted_id_1, {
            "retrieval_count": 2,
            "prevented_rework_count": 0,
            "ineffective_count": 5,
        })
        # Set Lesson B as created 45 days ago with 0 retrievals
        store.update_lesson(promoted_b_id, {
            "created": "2026-08-01",
            "retrieval_count": 0,
            "prevented_rework_count": 0,
            "ineffective_count": 0,
        })

        all_active = store.list_lessons()
        # Inactivity padding test: if last pipeline run was Aug 10 (51 days ago), only 9 active days elapsed
        spared = flag_low_utility(all_active, reference_date=date(2026, 9, 30), latest_run_date=date(2026, 8, 10))
        assert not any(f["id"] == promoted_b_id and "never_retrieved" in f["flag_reasons"] for f in spared)

        # But with recent pipeline activity (e.g. today), Lesson B decays
        flagged = flag_low_utility(all_active, reference_date=date(2026, 9, 30), latest_run_date=date(2026, 9, 30))
        assert len(flagged) == 2

        flagged_by_id = {f["id"]: f for f in flagged}
        assert "consistently_ineffective" in flagged_by_id[promoted_id_1]["flag_reasons"]
        assert "never_retrieved" in flagged_by_id[promoted_b_id]["flag_reasons"]


class patch_memorystore:
    """Context manager to monkeypatch MemoryStore in memory_cmd to use db_path."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._orig = memory_cmd.MemoryStore

    def __enter__(self):
        memory_cmd.MemoryStore = lambda *args, **kwargs: self._orig(self.db_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        memory_cmd.MemoryStore = self._orig
