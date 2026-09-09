"""Terminal MCP Console Drawer with high-capacity scrollback."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog, Static


class TerminalConsoleDrawer(Widget):
    """Bottom drawer displaying live output from terminal-mcp PTY execution."""

    DEFAULT_CSS = """
    TerminalConsoleDrawer {
        height: 10;
        min-height: 3;
        border: round $success;
        background: $surface;
        padding: 0 1;
    }
    TerminalConsoleDrawer.compact {
        height: 5;
    }
    TerminalConsoleDrawer.expanded {
        height: 22;
    }
    TerminalConsoleDrawer.collapsed {
        height: 3;
    }
    #drawer-title {
        height: 1;
        margin-bottom: 0;
    }
    #console-log {
        height: 1fr;
    }
    """

    def __init__(self, max_lines: int = 10000, **kwargs):
        super().__init__(**kwargs)
        self.max_lines = max_lines
        self.mode_index = 1  # 0: collapsed, 1: normal, 2: compact, 3: expanded
        self.auto_scroll = True
        self.line_count = 0

    def compose(self) -> ComposeResult:
        yield Static("🖥️ Console (terminal-mcp PTY) ── [Auto-Scroll: ON] (Press 't' to resize, 'f' to follow)", id="drawer-title")
        yield RichLog(max_lines=self.max_lines, auto_scroll=True, id="console-log")

    def toggle_size(self) -> None:
        """Cycle through heights: normal -> expanded -> collapsed -> compact -> normal."""
        self.remove_class("compact")
        self.remove_class("expanded")
        self.remove_class("collapsed")

        self.mode_index = (self.mode_index + 1) % 4
        if self.mode_index == 0:
            self.add_class("collapsed")
        elif self.mode_index == 2:
            self.add_class("compact")
        elif self.mode_index == 3:
            self.add_class("expanded")

    def snap_to_bottom(self) -> None:
        self.auto_scroll = True
        try:
            log_widget = self.query_one("#console-log", RichLog)
            log_widget.auto_scroll = True
            log_widget.scroll_end(animate=False)
            self._update_title()
        except Exception:
            pass

    def set_lines(self, lines: list[str]) -> None:
        """Replace all log content with the provided lines."""
        try:
            log_widget = self.query_one("#console-log", RichLog)
            log_widget.clear()
            self.line_count = 0
            for line in lines:
                self.line_count += 1
                log_widget.write(line)
            self._update_title()
        except Exception:
            pass

    def append_line(self, line: str) -> None:
        self.line_count += 1
        try:
            log_widget = self.query_one("#console-log", RichLog)
            log_widget.write(line)
            self._update_title()
        except Exception:
            pass

    def _update_title(self) -> None:
        title = self.query_one("#drawer-title", Static)
        scroll_status = "Auto-Scroll: ON" if self.auto_scroll else "SCROLL LOCKED"
        status_style = "bold green" if self.auto_scroll else "bold red"

        text = Text()
        text.append("🖥️ Console (terminal-mcp PTY) ── [", style="bold white")
        text.append(scroll_status, style=status_style)
        text.append(f"] [Lines: {self.line_count:,}] (Press 't' to resize, 'f' to follow)", style="bold white")
        title.update(text)
