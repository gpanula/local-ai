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


def test_lessons_tui_active_mode_delete(temp_env):
    """Test deleting an active lesson in active mode removes it from db, lessons.md, and wiki."""
    db_path, lessons_md, wiki_dir = temp_env

    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "lesson-active-01",
            "rule": "Always test error conditions directly.",
            "category": "Defensive Bash Scripting",
            "keywords": ["testing", "bash"],
            "source_task": "test.md",
        })
        store.insert_lesson({
            "id": "lesson-active-02",
            "rule": "Second active rule.",
            "category": "Defensive Bash Scripting",
            "keywords": ["testing"],
            "source_task": "test2.md",
        })
        lessons = store.list_lessons()
        from mcp_core.lessons_writer import write_all_lessons_to_markdown
        write_all_lessons_to_markdown(lessons, lessons_md)

    async def _run():
        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            # Switch to active mode via 't' key
            await pilot.press("t")
            assert app.mode == "active"
            assert len(app.active_lessons) == 2

            # Discard first active lesson
            app.action_discard()
            assert len(app.active_lessons) == 1
            assert app.active_lessons[0]["id"] == "lesson-active-02"

            with MemoryStore(db_path) as store:
                active_db = store.list_lessons()
                assert len(active_db) == 1
                assert active_db[0]["id"] == "lesson-active-02"

            # Check lessons.md is synced
            content = open(lessons_md, encoding="utf-8").read()
            assert "lesson-active-01" not in content
            assert "lesson-active-02" in content

            # Check wiki index is compiled
            index_path = os.path.join(wiki_dir, "index.md")
            assert os.path.exists(index_path)
            index_content = open(index_path, encoding="utf-8").read()
            assert "lesson-active-01" not in index_content
            assert "lesson-active-02" in index_content

    asyncio.run(_run())


def test_lessons_tui_active_mode_modify(temp_env):
    """Test modifying an active lesson in active mode updates db, lessons.md, and wiki."""
    db_path, lessons_md, wiki_dir = temp_env

    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "lesson-active-mod-01",
            "rule": "Original rule text.",
            "category": "Defensive Bash Scripting",
            "keywords": ["original"],
            "source_task": "test.md",
        })
        lessons = store.list_lessons()
        from mcp_core.lessons_writer import write_all_lessons_to_markdown
        write_all_lessons_to_markdown(lessons, lessons_md)

    async def _run():
        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            # Switch to active mode via tab key press
            await pilot.press("tab")
            assert app.mode == "active"

            # Trigger modify action
            app.action_modify()
            await pilot.pause()

            # Find modal and submit edits
            modal = app.screen
            assert isinstance(modal, EditLessonModal)
            rule_input = modal.query_one("#rule-input")
            rule_input.text = "Updated robust rule text."
            modal.action_save()
            await pilot.pause()

            # Verify store updated
            with MemoryStore(db_path) as store:
                updated = store.get_lesson("lesson-active-mod-01")
                assert updated is not None
                assert updated["rule"] == "Updated robust rule text."

            # Verify lessons.md updated
            content = open(lessons_md, encoding="utf-8").read()
            assert "Updated robust rule text." in content
            assert "Original rule text." not in content

            # Verify wiki updated
            index_path = os.path.join(wiki_dir, "index.md")
            assert os.path.exists(index_path)
            index_content = open(index_path, encoding="utf-8").read()
            assert "Updated robust rule text" in index_content

    asyncio.run(_run())


def test_lessons_tui_active_mode_delete_preserves_cursor_position(temp_env):
    """Test deleting an active lesson when not at top preserves cursor position instead of jumping to 0."""
    db_path, lessons_md, wiki_dir = temp_env

    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "lesson-act-00",
            "rule": "First rule text.",
            "category": "Testing",
            "keywords": ["test0"],
        })
        store.insert_lesson({
            "id": "lesson-act-01",
            "rule": "Second rule text to delete.",
            "category": "Testing",
            "keywords": ["test1"],
        })
        store.insert_lesson({
            "id": "lesson-act-02",
            "rule": "Third rule text that should become highlighted.",
            "category": "Testing",
            "keywords": ["test2"],
        })
        from mcp_core.lessons_writer import write_all_lessons_to_markdown
        write_all_lessons_to_markdown(store.list_lessons(), lessons_md)

    async def _run():
        app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            # Switch to active mode
            await pilot.press("t")
            assert app.mode == "active"
            assert len(app.active_lessons) == 3

            list_view = app.query_one("#lesson-list", LessonListView)
            detail_view = app.query_one("#lesson-detail", LessonDetailView)

            # Move cursor to index 1 (second item)
            list_view.index = 1
            await pilot.pause()
            assert list_view.index == 1
            assert list_view.get_selected_lesson()["id"] == "lesson-act-01"
            assert detail_view.lesson["id"] == "lesson-act-01"

            # Delete the second item
            app.action_discard()
            await pilot.pause()

            # Cursor must remain at index 1 (pointing to lesson-act-02), NOT reset to 0
            assert len(app.active_lessons) == 2
            assert list_view.index == 1
            assert list_view.get_selected_lesson()["id"] == "lesson-act-02"
            assert detail_view.lesson["id"] == "lesson-act-02"

            with MemoryStore(db_path) as store:
                remaining_ids = [l["id"] for l in store.list_lessons()]
                assert remaining_ids == ["lesson-act-00", "lesson-act-02"]

    asyncio.run(_run())

