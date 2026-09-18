"""Main Textual Application for Local AI Lessons Review & Knowledge Base Browser."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Label, Static

from mcp_core.lesson_linter import lint_lesson
from mcp_core.lessons_writer import append_lesson_to_markdown
from mcp_core.memory import DEFAULT_DB_PATH, MemoryStore
from mcp_core.wiki import generate_dashboard, generate_index, generate_log
from mcp_core.workspace import WORKSPACE_ROOT
from lessons_tui.widgets.edit_modal import EditLessonModal
from lessons_tui.widgets.lesson_detail import LessonDetailView
from lessons_tui.widgets.lesson_list import LessonListView

DEFAULT_LESSONS_MD = os.path.join(WORKSPACE_ROOT, "ollama_update", "lessons.md")
DEFAULT_WIKI_DIR = os.path.join(WORKSPACE_ROOT, "ollama_update", "wiki")


class LessonsReviewApp(App):
    """Interactive TUI for reviewing pending lessons and exploring active knowledge base."""

    CSS = """
    Screen {
        background: $background;
    }

    #top-bar {
        height: 3;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $primary;
    }

    #app-title {
        text-style: bold;
        color: $accent;
        width: 35;
    }

    #tabs-indicator {
        text-style: bold;
        width: 1fr;
    }

    #stats-badge {
        width: auto;
        color: $text-muted;
    }

    #main-container {
        height: 1fr;
        width: 100%;
    }

    #left-panel {
        width: 38;
        height: 100%;
        border-right: solid $primary-darken-2;
    }

    #panel-header {
        height: 1;
        padding: 0 1;
        background: $surface-lighten-1;
        color: $accent;
        text-style: bold;
    }

    #right-panel {
        width: 1fr;
        height: 100%;
    }

    #notification-bar {
        height: 1;
        background: $surface;
        color: $accent;
        padding: 0 1;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("tab", "switch_tab", "Switch Tab"),
        Binding("k", "keep", "Keep/Promote"),
        Binding("m", "modify", "Modify"),
        Binding("d", "discard", "Discard"),
        Binding("s", "skip", "Skip/Next"),
        Binding("a", "auto_safe", "Auto-Promote Safe"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        lessons_md: str = DEFAULT_LESSONS_MD,
        wiki_dir: str = DEFAULT_WIKI_DIR,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.lessons_md = lessons_md
        self.wiki_dir = wiki_dir
        self.mode: str = "pending"  # "pending" or "active"
        self.pending_lessons: List[Dict[str, Any]] = []
        self.active_lessons: List[Dict[str, Any]] = []
        try:
            with MemoryStore(self.db_path) as store:
                self.pending_lessons = store.list_pending_lessons()
                self.active_lessons = store.list_lessons()
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            yield Label("🧠 Local AI Lesson Manager", id="app-title")
            yield Static("[bold yellow]▶ [Tab] Pending Reviews[/bold yellow]  |  [dim][Tab] Active Knowledge Base[/dim]", id="tabs-indicator")
            yield Static("", id="stats-badge")

        with Horizontal(id="main-container"):
            with Vertical(id="left-panel"):
                yield Label("Pending Queue (0)", id="panel-header")
                yield LessonListView(id="lesson-list")
            with Vertical(id="right-panel"):
                yield LessonDetailView(id="lesson-detail")

        yield Static("Ready. Press 'k' to keep, 'm' to modify, 'd' to discard, 'Tab' to switch views.", id="notification-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._update_ui()

    def reload_data(self) -> None:
        """Fetch latest pending and active lessons from the database."""
        with MemoryStore(self.db_path) as store:
            self.pending_lessons = store.list_pending_lessons()
            self.active_lessons = store.list_lessons()

        self._update_ui()

    def _update_ui(self) -> None:
        try:
            list_view = self.query_one("#lesson-list", LessonListView)
            detail_view = self.query_one("#lesson-detail", LessonDetailView)
            tabs_indicator = self.query_one("#tabs-indicator", Static)
            stats_badge = self.query_one("#stats-badge", Static)
            panel_header = self.query_one("#panel-header", Label)
        except Exception:
            return

        # Count violations among pending
        pending_viols = sum(
            1 for p in self.pending_lessons
            if lint_lesson({"id": p.get("id"), "rule": p.get("proposed_rule", "")})
        )

        viol_str = f" | [bold red]🚨 {pending_viols} violating[/bold red]" if pending_viols > 0 else " | [bold green]✅ 0 violating[/bold green]"
        stats_badge.update(f"Pending: {len(self.pending_lessons)} | Active: {len(self.active_lessons)}{viol_str}")

        if self.mode == "pending":
            tabs_indicator.update(
                f"[bold yellow]▶ [Tab] Pending Reviews ({len(self.pending_lessons)})[/bold yellow]  |  [dim][Tab] Active Knowledge Base ({len(self.active_lessons)})[/dim]"
            )
            panel_header.update(f"Pending Queue ({len(self.pending_lessons)})")
            list_view.set_lessons(self.pending_lessons, is_pending=True)
            if self.pending_lessons:
                detail_view.display_lesson(self.pending_lessons[0], is_pending=True)
            else:
                detail_view.display_lesson(None, is_pending=True)
        else:
            tabs_indicator.update(
                f"[dim][Tab] Pending Reviews ({len(self.pending_lessons)})[/dim]  |  [bold cyan]▶ [Tab] Active Knowledge Base ({len(self.active_lessons)})[/bold cyan]"
            )
            panel_header.update(f"Active Knowledge ({len(self.active_lessons)})")
            list_view.set_lessons(self.active_lessons, is_pending=False)
            if self.active_lessons:
                detail_view.display_lesson(self.active_lessons[0], is_pending=False)
            else:
                detail_view.display_lesson(None, is_pending=False)

    @on(LessonListView.Selected)
    def on_lesson_selected(self, event: LessonListView.Selected) -> None:
        try:
            detail_view = self.query_one("#lesson-detail", LessonDetailView)
            detail_view.display_lesson(event.lesson, is_pending=event.is_pending)
        except Exception:
            pass

    def set_notification(self, text: str) -> None:
        try:
            bar = self.query_one("#notification-bar", Static)
            bar.update(text)
        except Exception:
            pass

    # --- Actions ---

    def action_switch_tab(self) -> None:
        """Toggle between Pending Reviews and Active Knowledge Base."""
        self.mode = "active" if self.mode == "pending" else "pending"
        self._update_ui()
        self.set_notification(f"Switched view to {self.mode.upper()} mode.")

    def action_refresh(self) -> None:
        """Reload all data from store."""
        self.reload_data()
        self.set_notification("Data refreshed from store.")

    def action_skip(self) -> None:
        """Move to the next lesson in the list."""
        list_view = self.query_one("#lesson-list", LessonListView)
        if list_view.index is not None and list_view.index + 1 < len(list_view.lessons):
            list_view.index += 1
            self.set_notification("Skipped to next lesson.")
        else:
            self.set_notification("Reached end of list.")

    def action_keep(self) -> None:
        """Promote the currently selected pending lesson."""
        if self.mode != "pending":
            self.set_notification("⚠️ Keep/Promote only applies to pending lessons.")
            return

        list_view = self.query_one("#lesson-list", LessonListView)
        lesson = list_view.get_selected_lesson()
        if not lesson:
            self.set_notification("⚠️ No lesson selected.")
            return

        lid = lesson.get("id")
        with MemoryStore(self.db_path) as store:
            promoted_id = store.promote_pending_lesson(lid)
            if promoted_id:
                promoted = store.get_lesson(promoted_id)
                if promoted:
                    append_lesson_to_markdown(promoted, self.lessons_md)
                self.recompile_wiki_after_change(1)
                self.set_notification(f"✅ Promoted lesson {promoted_id} and appended to lessons.md.")
            else:
                self.set_notification(f"⚠️ Failed to promote lesson {lid}.")

        self.reload_data()

    def action_modify(self) -> None:
        """Open modal dialog to edit lesson before promotion."""
        if self.mode != "pending":
            self.set_notification("⚠️ Modify only applies to pending lessons.")
            return

        list_view = self.query_one("#lesson-list", LessonListView)
        lesson = list_view.get_selected_lesson()
        if not lesson:
            self.set_notification("⚠️ No lesson selected.")
            return

        def handle_modal_result(edits: Optional[Dict[str, Any]]) -> None:
            if edits:
                lid = lesson.get("id")
                with MemoryStore(self.db_path) as store:
                    promoted_id = store.promote_pending_lesson(lid, edits=edits)
                    if promoted_id:
                        promoted = store.get_lesson(promoted_id)
                        if promoted:
                            append_lesson_to_markdown(promoted, self.lessons_md)
                        self.recompile_wiki_after_change(1)
                        self.set_notification(f"✏️ Modified & promoted lesson {promoted_id}.")
                self.reload_data()
            else:
                self.set_notification("Edit cancelled.")

        self.push_screen(EditLessonModal(lesson), handle_modal_result)

    def action_discard(self) -> None:
        """Delete current pending lesson (or active lesson with confirmation)."""
        list_view = self.query_one("#lesson-list", LessonListView)
        lesson = list_view.get_selected_lesson()
        if not lesson:
            self.set_notification("⚠️ No lesson selected.")
            return

        lid = lesson.get("id")
        with MemoryStore(self.db_path) as store:
            if self.mode == "pending":
                store.delete_pending_lesson(lid)
                self.set_notification(f"🗑️ Discarded pending lesson {lid}.")
            else:
                store.delete_lesson(lid)
                self.set_notification(f"🗑️ Removed active lesson {lid}.")

        self.reload_data()

    def action_auto_safe(self) -> None:
        """Auto-promote all compliant pending lessons while skipping violating ones."""
        if self.mode != "pending":
            self.set_notification("⚠️ Auto-promote only applies to pending lessons.")
            return

        promoted_count = 0
        skipped_count = 0
        with MemoryStore(self.db_path) as store:
            for item in self.pending_lessons:
                violations = lint_lesson({"id": item.get("id"), "rule": item.get("proposed_rule", "")})
                if violations:
                    skipped_count += 1
                    continue

                promoted_id = store.promote_pending_lesson(item["id"])
                if promoted_id:
                    promoted = store.get_lesson(promoted_id)
                    if promoted:
                        append_lesson_to_markdown(promoted, self.lessons_md)
                    promoted_count += 1

        if promoted_count > 0:
            self.recompile_wiki_after_change(promoted_count)

        self.reload_data()
        self.set_notification(
            f"🎉 Auto-promoted {promoted_count} safe lesson(s). {skipped_count} violating lesson(s) retained for review."
        )

    def recompile_wiki_after_change(self, count: int) -> None:
        """Helper to re-compile wiki markdown files after promoting lessons."""
        if not self.wiki_dir:
            return
        try:
            with MemoryStore(self.db_path) as store:
                updated_lessons = store.list_lessons()
            os.makedirs(self.wiki_dir, exist_ok=True)
            generate_index(updated_lessons, os.path.join(self.wiki_dir, "index.md"))
            generate_dashboard(updated_lessons, os.path.join(self.wiki_dir, "dashboard.md"))
            from datetime import datetime, timezone

            generate_log(
                [
                    {
                        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        "message": f"Wiki re-compiled after promoting {count} lesson(s) via TUI.",
                    }
                ],
                os.path.join(self.wiki_dir, "log.md"),
            )
        except Exception:
            pass


def launch_lessons_tui(
    db_path: str = DEFAULT_DB_PATH,
    lessons_md: str = DEFAULT_LESSONS_MD,
    wiki_dir: str = DEFAULT_WIKI_DIR,
) -> None:
    """Launch the LessonsReviewApp."""
    app = LessonsReviewApp(db_path=db_path, lessons_md=lessons_md, wiki_dir=wiki_dir)
    app.run()


if __name__ == "__main__":
    launch_lessons_tui()
