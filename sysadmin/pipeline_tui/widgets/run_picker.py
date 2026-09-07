"""Interactive Run Picker Modal Screen for selecting past runs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static


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
            yield DataTable(id="picker-table", cursor_type="row")
            yield Static("[↑/↓] Navigate  │  [Enter] Select Run  │  [Esc] Cancel", id="picker-footer")

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

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            table = self.query_one("#picker-table", DataTable)
            if table.cursor_row is not None and 0 <= table.cursor_row < len(self.filtered_runs):
                self.dismiss(self.filtered_runs[table.cursor_row])
