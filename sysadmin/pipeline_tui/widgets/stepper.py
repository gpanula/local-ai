"""Visual DAG stepper widget for PipelineWatch."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

STAGES = [
    ("architect", "Architect"),
    ("orchestrator", "Orchestrator"),
    ("reviewer", "Reviewer"),
    ("security", "Security"),
    ("coder", "Coder"),
    ("sysadmin", "Sysadmin"),
]


def normalize_stage(stage: str) -> str:
    """Normalize alias and role names to standard 6-stage pipeline keys."""
    s = (stage or "").lower().strip()
    aliases = {
        "orchestrate": "orchestrator",
        "author": "coder",
        "lint": "reviewer",
        "review": "reviewer",
        "execute": "sysadmin",
        "execution": "sysadmin",
        "dispatch": "coder",
    }
    return aliases.get(s, s)


class StageBadge(Static):
    """Clickable badge for an individual pipeline stage."""

    DEFAULT_CSS = """
    StageBadge {
        width: auto;
        height: 1;
    }
    StageBadge:hover {
        text-style: underline bold;
    }
    """

    def __init__(self, stage: str, label: str, **kwargs):
        super().__init__(**kwargs)
        self.stage = stage
        self.label = label

    def on_click(self) -> None:
        self.post_message(PipelineStepper.StageSelected(self.stage))


class PipelineStepper(Widget):
    """Horizontal visual stepper indicating current pipeline phase and iteration."""

    class StageSelected(Message):
        """Posted when a stage badge is clicked."""
        def __init__(self, stage: str) -> None:
            self.stage = stage
            super().__init__()

    DEFAULT_CSS = """
    PipelineStepper {
        height: 3;
        background: $background;
        padding: 0 1;
        border-bottom: solid $panel;
        layout: horizontal;
        align-vertical: middle;
        overflow-x: auto;
    }
    #stepper-content {
        display: none;
    }
    .stepper-iteration {
        width: auto;
        height: 1;
    }
    .stage-arrow {
        width: auto;
        height: 1;
        color: $text-muted;
    }
    .stepper-nav-hint {
        width: auto;
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_stage = "architect"
        self.selected_stage = "architect"
        self.iteration = 1
        self.max_retries = 1
        self.outcome = "in_progress"

    def compose(self) -> ComposeResult:
        yield Static(id="stepper-content")
        yield Static(id="stepper-iteration", classes="stepper-iteration")
        for i, (key, label) in enumerate(STAGES):
            if i > 0:
                yield Static(" ──> ", classes="stage-arrow")
            yield StageBadge(stage=key, label=label, id=f"stage-badge-{key}")
        yield Static(" │ [←/→] or Click Stage", classes="stepper-nav-hint")

    def update_state(self, state) -> None:
        self.current_stage = state.current_stage
        self.selected_stage = getattr(state, "selected_stage", self.selected_stage)
        self.iteration = getattr(state, "active_iteration_idx", getattr(state, "current_iteration_num", 1))
        self.max_retries = state.max_retries
        self.outcome = state.outcome
        self.refresh_display()

    def refresh_display(self) -> None:
        try:
            it_widget = self.query_one("#stepper-iteration", Static)
        except Exception:
            return

        it_text = Text()
        it_text.append(f" Iteration {self.iteration}/{self.max_retries} │ ", style="bold white on blue")
        it_widget.update(it_text)

        norm_cur = normalize_stage(self.current_stage)
        norm_sel = normalize_stage(self.selected_stage)
        stage_order = [s[0] for s in STAGES]
        curr_idx = stage_order.index(norm_cur) if norm_cur in stage_order else -1
        is_finished = norm_cur in ("finished", "complete") or self.outcome in (
            "approved", "finished", "complete", "aborted", "failed"
        )

        full_text = Text()
        full_text.append(f" Iteration {self.iteration}/{self.max_retries} │ ", style="bold white on blue")

        for i, (key, label) in enumerate(STAGES):
            if i > 0:
                full_text.append(" ──> ", style="dim")

            is_selected = (key == norm_sel)
            prefix = "▶ " if is_selected else ""
            suffix = " ◀" if is_selected else ""

            if is_finished or i < curr_idx:
                badge = f"{prefix}[✓ {label}]{suffix}"
                style = "bold white on green" if is_selected else "green"
            elif i == curr_idx:
                if self.outcome in ("failed", "aborted"):
                    badge = f"{prefix}[✗ {label}]{suffix}"
                    style = "bold white on red" if is_selected else "bold red"
                else:
                    badge = f"{prefix}[⟳ {label}]{suffix}"
                    style = "bold white on yellow" if is_selected else "bold yellow"
            else:
                badge = f"{prefix}[  {label}]{suffix}"
                style = "bold white on blue" if is_selected else "dim"

            full_text.append(badge, style=style)

            try:
                badge_widget = self.query_one(f"#stage-badge-{key}", StageBadge)
                t = Text()
                t.append(badge, style=style)
                badge_widget.update(t)
            except Exception:
                pass

        full_text.append(" │ [←/→] Navigate Stages", style="dim cyan")
        try:
            content = self.query_one("#stepper-content", Static)
            content.update(full_text)
        except Exception:
            pass
