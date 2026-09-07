"""Header widget for PipelineWatch."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class PipelineHeader(Widget):
    """Header bar displaying Run ID, Hardware Tier, Model, Context Budget, and Status."""

    DEFAULT_CSS = """
    PipelineHeader {
        dock: top;
        height: 3;
        background: $surface;
        color: $text;
        border-bottom: heavy $accent;
        padding: 0 1;
    }
    #header-title {
        text-style: bold;
        color: $warning;
    }
    #header-meta {
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.run_id = "Initializing..."
        self.task_file = "None"
        self.model = "None"
        self.tier = "8gb"
        self.status = "IDLE"
        self.context_tokens = "0 / 8,192 tk"
        self.speed = "0.0 tok/s"
        self.elapsed = "00:00"

    def compose(self) -> ComposeResult:
        yield Static(id="header-content")

    def update_state(self, state) -> None:
        self.run_id = state.run_id or "run-active"
        self.task_file = state.task_file or "interactive"
        self.tier = (state.tier or "8gb").upper()
        self.model = state.models.get("author") or state.models.get("coder") or "ollama"
        self.status = state.current_stage.upper()

        cur_it = state.current_iteration()
        tb = cur_it.context_window.get("token_breakdown", {})
        if tb:
            tot = tb.get("total", 0)
            lim = tb.get("limit", 8192)
            pct = int((tot / lim) * 100) if lim else 0
            self.context_tokens = f"{tot:,} / {lim:,} tk ({pct}%)"
        
        stat = cur_it.stats
        if isinstance(stat, dict) and "eval_rate" in stat:
            self.speed = f"{stat['eval_rate']} tok/s"

        self.refresh_display()

    def refresh_display(self) -> None:
        try:
            content = self.query_one("#header-content", Static)
        except Exception:
            return

        text = Text()
        text.append("⚡ PIPELINE WATCH  ", style="bold yellow")
        text.append(f"[{self.run_id}] ", style="bold cyan")
        text.append(f"Task: {self.task_file}  ", style="dim")
        text.append(f"Tier: {self.tier}  ", style="magenta")
        text.append(f"Model: {self.model}  ", style="green")
        text.append(f"Ctx: {self.context_tokens}  ", style="blue")
        text.append(f"State: {self.status}", style="bold green" if self.status in ("APPROVED", "FINISHED") else "bold yellow")
        content.update(text)
