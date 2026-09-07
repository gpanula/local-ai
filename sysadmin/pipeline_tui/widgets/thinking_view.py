"""Active Thinking widget for monitoring model raw deliberation & chain-of-thought."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static


class ActiveThinkingView(Widget):
    """Scrollable view displaying the model's raw internal monologue / deliberation."""

    DEFAULT_CSS = """
    ActiveThinkingView {
        height: 10;
        min-height: 5;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }
    #thinking-header {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #thinking-scroll {
        height: 1fr;
    }
    #thinking-body {
        color: $text;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.text_content = "Waiting for model deliberation..."

    def compose(self) -> ComposeResult:
        yield Static("💭 Active Thinking (Raw Chain-of-Thought)", id="thinking-header")
        with VerticalScroll(id="thinking-scroll"):
            yield Static(self.text_content, id="thinking-body")

    def update_thinking(self, text: str) -> None:
        self.text_content = text or "(No thinking tokens recorded for this iteration)"
        try:
            body = self.query_one("#thinking-body", Static)
            body.update(self.text_content)
            scroll = self.query_one("#thinking-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            pass
