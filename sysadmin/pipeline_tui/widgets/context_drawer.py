"""Context Window Drawer widget with token budget meter and sub-divided tabs."""

from __future__ import annotations

import json
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static, TabbedContent, TabPane


class ContextWindowDrawer(Widget):
    """Collapsible drawer showing the breakdown of the model's active context window."""

    DEFAULT_CSS = """
    ContextWindowDrawer {
        height: 12;
        min-height: 4;
        border: round $warning;
        background: $surface;
        padding: 0 1;
        display: block;
    }
    ContextWindowDrawer:focus-within {
        border: double $accent;
    }
    ContextWindowDrawer.collapsed {
        height: 3;
        min-height: 3;
    }
    #ctx-meter {
        height: 2;
        margin-bottom: 0;
    }
    .ctx-scroll {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.is_collapsed = False
        self.raw_data = {}

    def compose(self) -> ComposeResult:
        yield Static("📦 Context Window: Waiting for prompt dispatch...", id="ctx-meter")
        with TabbedContent(id="ctx-tabs"):
            with TabPane("1. Rules", id="tab-ctx-rules"):
                with VerticalScroll(classes="ctx-scroll"):
                    yield Static("No system rules recorded.", id="ctx-rules-body")

            with TabPane("2. Tools", id="tab-ctx-tools"):
                with VerticalScroll(classes="ctx-scroll"):
                    yield Static("No tools declared.", id="ctx-tools-body")

            with TabPane("3. Lessons", id="tab-ctx-lessons"):
                with VerticalScroll(classes="ctx-scroll"):
                    yield Static("No lessons injected.", id="ctx-lessons-body")

            with TabPane("4. Task Prompt", id="tab-ctx-prompt"):
                with VerticalScroll(classes="ctx-scroll"):
                    yield Static("No task prompt recorded.", id="ctx-prompt-body")

            with TabPane("5. Rework Feedback", id="tab-ctx-rework"):
                with VerticalScroll(classes="ctx-scroll"):
                    yield Static("No rework feedback (first iteration).", id="ctx-rework-body")

    def toggle(self) -> None:
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.add_class("collapsed")
            try:
                self.query_one("#ctx-tabs").display = False
            except Exception:
                pass
        else:
            self.remove_class("collapsed")
            try:
                self.query_one("#ctx-tabs").display = True
            except Exception:
                pass

    def update_context(self, ctx_data: dict, stage: str = "author", model: str = "") -> None:
        self.raw_data = ctx_data or {}
        tb = self.raw_data.get("token_breakdown", {})
        tot = tb.get("total", 0)
        lim = tb.get("limit", 8192)
        pct = int((tot / lim) * 100) if lim else 0

        # Update Meter
        meter = Text()
        meter.append("📦 Context Window ", style="bold yellow")
        meter.append(f"── [Stage: {stage.upper()}] ", style="bold cyan")
        if model:
            meter.append(f"[{model}] ", style="bold green")
        meter.append(f"[{tot:,} / {lim:,} tk ({pct}%)] (Toggle: 'c') │ ", style="bold yellow")
        meter.append(f"Rules: {tb.get('rules', 0):,}  ", style="cyan")
        meter.append(f"Tools: {tb.get('tools', 0):,}  ", style="blue")
        meter.append(f"Lessons: {tb.get('lessons', 0):,}  ", style="magenta")
        meter.append(f"Prompt: {tb.get('prompt', 0):,}  ", style="green")
        meter.append(f"Rework: {tb.get('feedback', 0):,}", style="red")

        try:
            self.query_one("#ctx-meter", Static).update(meter)
        except Exception:
            pass

        # Update Tabs
        rules = self.raw_data.get("system_rules") or "No system rules loaded."
        tools = self.raw_data.get("tools") or []
        lessons = self.raw_data.get("lessons") or []
        prompt = self.raw_data.get("user_prompt") or "No prompt loaded."
        rework = self.raw_data.get("rework_feedback") or "(No rework critique for this iteration)"

        try:
            self.query_one("#ctx-rules-body", Static).update(rules)
            self.query_one("#ctx-tools-body", Static).update(json.dumps(tools, indent=2, ensure_ascii=False))
            self.query_one("#ctx-lessons-body", Static).update(json.dumps(lessons, indent=2, ensure_ascii=False))
            self.query_one("#ctx-prompt-body", Static).update(prompt)
            self.query_one("#ctx-rework-body", Static).update(rework)
        except Exception:
            pass
