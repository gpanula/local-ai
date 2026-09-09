"""Interactive Run Picker Modal Screen for selecting past runs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static


class ReplayDataTable(DataTable):
    """DataTable with responsive horizontal and vertical mouse wheel scrolling."""

    DEFAULT_CSS = """
    ReplayDataTable {
        height: 1fr;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-color: $accent;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $secondary;
        scrollbar-background: $panel;
    }
    """

    def _scroll_right_for_pointer(self, *, animate: bool = False, **kwargs) -> bool:
        return self._scroll_to(min(self.max_scroll_x, self.scroll_target_x + 12), self.scroll_target_y, animate=False)

    def _scroll_left_for_pointer(self, *, animate: bool = False, **kwargs) -> bool:
        return self._scroll_to(max(0, self.scroll_target_x - 12), self.scroll_target_y, animate=False)

    def _scroll_down_for_pointer(self, *, animate: bool = False, **kwargs) -> bool:
        return self._scroll_to(self.scroll_target_x, min(self.max_scroll_y, self.scroll_target_y + 3), animate=False)

    def _scroll_up_for_pointer(self, *, animate: bool = False, **kwargs) -> bool:
        return self._scroll_to(self.scroll_target_x, max(0, self.scroll_target_y - 3), animate=False)


class RunPickerModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen displaying available pipeline runs for replay."""

    DEFAULT_CSS = """
    RunPickerModal {
        align: center middle;
    }
    #picker-container {
        width: 85%;
        height: 75%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #picker-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #picker-search {
        margin-bottom: 1;
    }
    #picker-table {
        height: 1fr;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-color: $accent;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $secondary;
        scrollbar-background: $panel;
    }
    #picker-footer {
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(self, runs: List[Dict[str, Any]], **kwargs):
        super().__init__(**kwargs)
        self.all_runs = runs
        self.filtered_runs = list(runs)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-container"):
            yield Static("📜 Past Pipeline Runs (Replay Catalog)", id="picker-title")
            yield Input(placeholder="Type to filter runs (e.g. backup, bootstrap, approved)...", id="picker-search")
            yield ReplayDataTable(id="picker-table", cursor_type="row")
            yield Static(
                "[↑/↓] Navigate  │  [Side Wheel / Shift+Wheel / ←/→] Side Scroll  │  [Enter] Select Run  │  [Esc] Cancel",
                id="picker-footer",
            )

    def on_mount(self) -> None:
        table = self.query_one("#picker-table", DataTable)
        table.add_columns("Run ID", "Timestamp", "Outcome", "Model", "Task / Prompt")
        self._populate_table()
        self.query_one("#picker-search", Input).focus()

    def _populate_table(self) -> None:
        table = self.query_one("#picker-table", DataTable)
        table.clear()
        for idx, run in enumerate(self.filtered_runs):
            outcome = run.get("outcome", "").upper()
            prompt = (run.get("prompt") or run.get("task_file") or "").replace("\n", " ")[:60]
            table.add_row(
                run.get("id", ""),
                run.get("timestamp", "")[:19].replace("T", " "),
                outcome,
                run.get("model", ""),
                prompt,
                key=str(idx),
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        if not query:
            self.filtered_runs = list(self.all_runs)
        else:
            self.filtered_runs = [
                r for r in self.all_runs
                if query in r.get("id", "").lower()
                or query in r.get("prompt", "").lower()
                or query in r.get("task_file", "").lower()
                or query in r.get("outcome", "").lower()
                or query in r.get("model", "").lower()
            ]
        self._populate_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value
        try:
            idx = int(row_key)
            if 0 <= idx < len(self.filtered_runs):
                self.dismiss(self.filtered_runs[idx])
                return
        except Exception:
            pass
        self.dismiss(None)

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        try:
            table = self.query_one("#picker-table", ReplayDataTable)
            table._scroll_left_for_pointer()
            event.stop()
        except Exception:
            pass

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        try:
            table = self.query_one("#picker-table", ReplayDataTable)
            table._scroll_right_for_pointer()
            event.stop()
        except Exception:
            pass

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        try:
            table = self.query_one("#picker-table", ReplayDataTable)
            if event.shift or event.ctrl:
                table._scroll_right_for_pointer()
            else:
                table._scroll_down_for_pointer()
            event.stop()
        except Exception:
            pass

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        try:
            table = self.query_one("#picker-table", ReplayDataTable)
            if event.shift or event.ctrl:
                table._scroll_left_for_pointer()
            else:
                table._scroll_up_for_pointer()
            event.stop()
        except Exception:
            pass

    def on_key(self, event) -> None:
        try:
            table = self.query_one("#picker-table", DataTable)
            search = self.query_one("#picker-search", Input)
        except Exception:
            return

        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            if table.cursor_row is not None and 0 <= table.cursor_row < len(self.filtered_runs):
                self.dismiss(self.filtered_runs[table.cursor_row])
        elif event.key == "down":
            table.action_cursor_down()
            event.stop()
        elif event.key == "up":
            table.action_cursor_up()
            event.stop()
        elif event.key == "pageup":
            table.scroll_page_up(animate=False)
            event.stop()
        elif event.key == "pagedown":
            table.scroll_page_down(animate=False)
            event.stop()
        elif event.key in ("left", "bracketleft") and (not search.has_focus or event.key == "bracketleft" or search.cursor_position == 0):
            table.scroll_to(max(0, table.scroll_target_x - 12), table.scroll_target_y, animate=False)
            if not search.has_focus or event.key == "bracketleft":
                event.stop()
        elif event.key in ("right", "bracketright") and (not search.has_focus or event.key == "bracketright" or search.cursor_position == len(search.value)):
            table.scroll_to(min(table.max_scroll_x, table.scroll_target_x + 12), table.scroll_target_y, animate=False)
            if not search.has_focus or event.key == "bracketright":
                event.stop()
