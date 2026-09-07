"""Visual DAG stepper widget for PipelineWatch."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

STAGES = [
    ("orchestrate", "Orchestrate"),
    ("author", "Author"),
    ("lint", "Pre-Flight Lint"),
    ("review", "Reviewer Gate"),
    ("execute", "Execution"),
]


class PipelineStepper(Widget):
    """Horizontal visual stepper indicating current pipeline phase and iteration."""

    DEFAULT_CSS = """
    PipelineStepper {
        height: 3;
        background: $background;
        padding: 0 1;
        border-bottom: solid $panel;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_stage = "idle"
        self.selected_stage = "author"
        self.iteration = 1
        self.max_retries = 3
        self.outcome = "in_progress"

    def compose(self) -> ComposeResult:
        yield Static(id="stepper-content")

    def update_state(self, state) -> None:
        self.current_stage = state.current_stage
        self.selected_stage = getattr(state, "selected_stage", self.selected_stage)
        self.iteration = state.active_iteration_idx
        self.max_retries = state.max_retries
        self.outcome = state.outcome
        self.refresh_display()

    def refresh_display(self) -> None:
        try:
            content = self.query_one("#stepper-content", Static)
        except Exception:
            return

        text = Text()
        text.append(f" Iteration {self.iteration}/{self.max_retries} │ ", style="bold white on blue")

        stage_order = ["orchestrate", "author", "lint", "review", "execute"]
        curr_idx = stage_order.index(self.current_stage) if self.current_stage in stage_order else -1
        is_finished = self.current_stage == "finished"

        for i, (key, label) in enumerate(STAGES):
            if i > 0:
                text.append(" ──> ", style="dim")

            is_selected = (key == self.selected_stage)
            prefix = "▶ " if is_selected else ""
            suffix = " ◀" if is_selected else ""

            if is_finished:
                if self.outcome in ("approved", "finished"):
                    badge = f"{prefix}[✓ {label}]{suffix}"
                    style = "bold black on green" if is_selected else "bold green"
                else:
                    badge = f"{prefix}[✗ {label}]{suffix}"
                    style = "bold white on red" if is_selected else "bold red"
            elif curr_idx == i:
                badge = f"{prefix}[⟳ {label}]{suffix}"
                style = "bold white on dark_goldenrod" if is_selected else "bold black on yellow"
            elif curr_idx > i:
                badge = f"{prefix}[✓ {label}]{suffix}"
                style = "bold black on light_green" if is_selected else "green"
            else:
                badge = f"{prefix}[  {label}]{suffix}"
                style = "bold white on blue" if is_selected else "dim"

            text.append(badge, style=style)

        text.append(" │ [←/→] Navigate Stages", style="dim cyan")
        content.update(text)
