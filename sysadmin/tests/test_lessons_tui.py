"""Unit tests for the LessonsReviewApp Textual TUI."""

from __future__ import annotations

import asyncio
import os
import pytest

from mcp_core.memory import MemoryStore
from lessons_tui.app import LessonsReviewApp
from lessons_tui.widgets.edit_modal import EditLessonModal
from lessons_tui.widgets.lesson_detail import LessonDetailView
from lessons_tui.widgets.lesson_list import LessonListView


@pytest.fixture
def temp_env(tmp_path):
    """Provide isolated database, lessons.md, and wiki dir."""
    db_path = str(tmp_path / "memory.db")
    lessons_md = str(tmp_path / "lessons.md")
    wiki_dir = str(tmp_path / "wiki")
    os.makedirs(wiki_dir, exist_ok=True)
    return db_path, lessons_md, wiki_dir


def test_lessons_tui_app_lifecycle(temp_env):
    """Test that LessonsReviewApp mounts cleanly and loads data."""
    db_path, lessons_md, wiki_dir = temp_env

    # Seed with one pending and one active lesson
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson({
            "id": "pending-test-01",
            "proposed_rule": "Always quote variables in bash scripts.",
            "category": "ShellCheck",
            "keywords": ["SC2086", "quoting"],
        })
        store.insert_lesson({
            "id": "lesson-test-01",
            "rule": "Never nest script content inside subshell strings.",
            "category": "Defensive Bash Scripting",
            "keywords": ["subshell", "strings"],
        })

    async def _run():
        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            assert app.mode == "pending"
            assert len(app.pending_lessons) == 1
            assert len(app.active_lessons) == 1

            list_view = app.query_one("#lesson-list", LessonListView)
            assert len(list_view.lessons) == 1

            detail_view = app.query_one("#lesson-detail", LessonDetailView)
            assert detail_view.lesson is not None
            assert detail_view.lesson["id"] == "pending-test-01"

            # Test tab switching
            app.action_switch_tab()
            assert app.mode == "active"
            assert len(list_view.lessons) == 1
            assert list_view.lessons[0]["id"] == "lesson-test-01"

            # Switch back
            app.action_switch_tab()
            assert app.mode == "pending"

    asyncio.run(_run())


def test_lessons_tui_keep_action(temp_env):
    """Test promoting a pending lesson via action_keep."""
    db_path, lessons_md, wiki_dir = temp_env

    with MemoryStore(db_path) as store:
        store.stage_pending_lesson({
            "id": "pending-promote-01",
            "proposed_rule": "Deterministic binary isolation required.",
            "category": "Defensive Scripting",
            "keywords": ["binary", "isolation"],
        })

    async def _run():
        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            assert len(app.pending_lessons) == 1
            app.action_keep()

            # Pending queue is now empty and lesson is promoted
            assert len(app.pending_lessons) == 0
            assert len(app.active_lessons) == 1

            with MemoryStore(db_path) as store:
                assert len(store.list_pending_lessons()) == 0
                active = store.list_lessons()
                assert len(active) == 1
                assert active[0]["rule"] == "Deterministic binary isolation required."

            # Verified written to markdown
            assert os.path.exists(lessons_md)
            content = open(lessons_md, encoding="utf-8").read()
            assert "Deterministic binary isolation required." in content

    asyncio.run(_run())


def test_lessons_tui_discard_action(temp_env):
    """Test discarding a pending lesson via action_discard."""
    db_path, lessons_md, wiki_dir = temp_env

    with MemoryStore(db_path) as store:
        store.stage_pending_lesson({
            "id": "pending-discard-01",
            "proposed_rule": "Some low quality rule.",
            "category": "Testing",
            "keywords": ["test"],
        })

    async def _run():
        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            assert len(app.pending_lessons) == 1
            app.action_discard()

            assert len(app.pending_lessons) == 0
            assert len(app.active_lessons) == 0

            with MemoryStore(db_path) as store:
                assert len(store.list_pending_lessons()) == 0
                assert len(store.list_lessons()) == 0

    asyncio.run(_run())


def test_lessons_tui_auto_safe_action(temp_env):
    """Test action_auto_safe promotes clean lessons and leaves violating ones."""
    db_path, lessons_md, wiki_dir = temp_env

    with MemoryStore(db_path) as store:
        # Safe lesson
        store.stage_pending_lesson({
            "id": "pending-safe-01",
            "proposed_rule": "Always quote variables to prevent word splitting.",
            "category": "ShellCheck",
            "keywords": ["quoting"],
        })
        # Violating lesson (violates TOOL_CONTRACT)
        store.stage_pending_lesson({
            "id": "pending-viol-02",
            "proposed_rule": "Avoid using write_file in future scripts.",
            "category": "ToolContract",
            "keywords": ["write_file"],
        })

    async def _run():
        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            assert len(app.pending_lessons) == 2
            app.action_auto_safe()

            # Safe promoted, violating retained
            assert len(app.pending_lessons) == 1
            assert app.pending_lessons[0]["id"] == "pending-viol-02"
            assert len(app.active_lessons) == 1
            assert app.active_lessons[0]["rule"] == "Always quote variables to prevent word splitting."

    asyncio.run(_run())


def test_edit_modal_validation():
    """Test EditLessonModal live invariant linter preview."""
    lesson = {
        "id": "pending-edit-01",
        "category": "ShellCheck",
        "proposed_rule": "Safe rule content.",
        "keywords": ["quoting"],
    }

    async def _run():
        modal = EditLessonModal(lesson)
        app = LessonsReviewApp()
        async with app.run_test() as pilot:
            await app.push_screen(modal)
            # Check initial clean status
            lint_box = modal.query_one("#lint-status")
            assert "Compliant" in str(lint_box.render())

            # Update text to violating rule
            rule_area = modal.query_one("#rule-input")
            rule_area.text = "Always avoid using write_file for scripts"
            await pilot.pause()

            # Check updated warning status
            assert "violation(s) detected" in str(lint_box.render())

    asyncio.run(_run())


def test_lesson_list_click_selection(temp_env):
    """Test clicking and keyboard selecting items in LessonListView does not raise TypeError."""
    db_path, lessons_md, wiki_dir = temp_env

    with MemoryStore(db_path) as store:
        store.stage_pending_lesson({
            "id": "pending-item-01",
            "proposed_rule": "First rule content.",
            "category": "Testing",
            "keywords": ["test1"],
        })
        store.stage_pending_lesson({
            "id": "pending-item-02",
            "proposed_rule": "Second rule content.",
            "category": "Testing",
            "keywords": ["test2"],
        })

    async def _run():
        from lessons_tui.widgets.lesson_list import LessonItemWidget
        from textual.widgets._list_item import ListItem

        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            list_view = app.query_one("#lesson-list", LessonListView)
            detail_view = app.query_one("#lesson-detail", LessonDetailView)
            assert detail_view.lesson["id"] == "pending-item-01"

            # Simulate mouse click on child of second item (triggers ListItem._ChildClicked -> ListView._on_list_item__child_clicked)
            item2 = list_view.children[1]
            assert isinstance(item2, LessonItemWidget)
            event = ListItem._ChildClicked(item2)
            list_view._on_list_item__child_clicked(event)
            await pilot.pause()

            # Verified detail view updated to second item without TypeError
            assert detail_view.lesson["id"] == "pending-item-02"

            # Also simulate pressing Enter / selecting item
            list_view.index = 0
            list_view.post_message(list_view.Selected(list_view, list_view.children[0], 0))
            await pilot.pause()
            assert detail_view.lesson["id"] == "pending-item-01"

    asyncio.run(_run())
