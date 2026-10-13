"""List widget for browsing pending or active lessons."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from mcp_core.lesson_linter import lint_lesson


class LessonItemWidget(ListItem):
    """Custom list item widget representing a single lesson row."""

    DEFAULT_CSS = """
    LessonItemWidget {
        padding: 0 1;
        height: auto;
    }
    LessonItemWidget:hover {
        background: $surface-lighten-1;
    }
    LessonItemWidget.-selected {
        background: $primary-darken-2;
    }
    """

    def __init__(self, lesson: Dict[str, Any], is_pending: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.lesson = lesson
        self.is_pending = is_pending

    def compose(self) -> ComposeResult:
        yield Static(self._build_text(), id="lesson-label")

    def _build_text(self) -> Text:
        lid = self.lesson.get("id") or self.lesson.get("lesson_id") or "unknown"
        cat = self.lesson.get("category", "General")
        rule = self.lesson.get("rule") or self.lesson.get("proposed_rule") or ""
        ltype = self.lesson.get("lesson_type", "solved_pattern")

        # Invariant check
        violations = lint_lesson({"id": lid, "rule": rule})
        lint_icon = "🚨" if violations else "✅"

        # Type badge
        if ltype == "hard_failure":
            type_badge = "[FAIL]"
            badge_color = "red bold"
        elif ltype == "solved_pattern":
            type_badge = "[PASS]"
            badge_color = "green bold"
        else:
            type_badge = "[RULE]"
            badge_color = "cyan bold"

        text = Text()
        text.append(f"{lint_icon} ")
        text.append(f"{type_badge} ", style=badge_color)
        text.append(f"{lid} ", style="bold white")
        text.append(f"({cat})", style="dim cyan")
        if rule:
            preview = rule[:45] + "..." if len(rule) > 45 else rule
            text.append(f"\n   ↳ {preview}", style="dim")

        return text

    def update_content(self, lesson: Optional[Dict[str, Any]] = None) -> None:
        """Refresh this item's visual representation without recreating the widget."""
        if lesson is not None:
            self.lesson = lesson
        try:
            static = self.query_one("#lesson-label", Static)
            static.update(self._build_text())
        except Exception:
            pass


class LessonListView(ListView):
    """List view managing lessons navigation."""

    DEFAULT_CSS = """
    LessonListView {
        width: 100%;
        height: 1fr;
        border: solid $secondary;
        background: $surface;
    }
    """

    class LessonSelected(Message):
        """Emitted when a lesson is highlighted/selected in the list."""

        def __init__(self, lesson: Dict[str, Any], is_pending: bool):
            super().__init__()
            self.lesson = lesson
            self.is_pending = is_pending

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lessons: List[Dict[str, Any]] = []
        self.is_pending: bool = True

    def set_lessons(
        self,
        lessons: List[Dict[str, Any]],
        is_pending: bool = True,
        keep_index: Optional[int] = None,
    ) -> None:
        """Populate the list with given lessons."""
        self.lessons = lessons
        self.is_pending = is_pending
        self.clear()

        for lesson in self.lessons:
            self.append(LessonItemWidget(lesson, is_pending=is_pending))

        if self.lessons:
            target_idx = (
                keep_index
                if (keep_index is not None and 0 <= keep_index < len(self.lessons))
                else 0
            )
            self.index = target_idx
            self.post_message(self.LessonSelected(self.lessons[target_idx], self.is_pending))
        else:
            self.index = None

    def remove_lesson_at(self, index: int) -> Optional[Dict[str, Any]]:
        """Remove lesson at index in place without clearing the list or resetting scroll."""
        if not (0 <= index < len(self.lessons)):
            return None

        removed = self.lessons.pop(index)
        self.pop(index)

        if not self.lessons:
            self.index = None
            return removed

        new_idx = min(index, len(self.lessons) - 1)
        self.index = new_idx
        self.post_message(self.LessonSelected(self.lessons[new_idx], self.is_pending))
        return removed

    def update_lesson_at(self, index: int, updated: Dict[str, Any]) -> None:
        """Update an existing lesson at index in place without clearing the list."""
        if not (0 <= index < len(self.lessons)):
            return
        self.lessons[index] = updated
        if index < len(self.children):
            child = self.children[index]
            if isinstance(child, LessonItemWidget):
                child.update_content(updated)
        self.post_message(self.LessonSelected(updated, self.is_pending))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, LessonItemWidget):
            self.post_message(self.LessonSelected(event.item.lesson, self.is_pending))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and isinstance(event.item, LessonItemWidget):
            self.post_message(self.LessonSelected(event.item.lesson, self.is_pending))

    def get_selected_lesson(self) -> Optional[Dict[str, Any]]:
        """Return the currently highlighted lesson dictionary."""
        if self.index is not None and 0 <= self.index < len(self.lessons):
            return self.lessons[self.index]
        return None

