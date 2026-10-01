"""Detail view showing complete lesson context, rule, critique, and invariant analysis."""

from __future__ import annotations

from typing import Any, Dict, Optional

from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Label, Static

from mcp_core.lesson_linter import lint_lesson


class LessonDetailView(VerticalScroll):
    """Rich detail viewer for the currently selected lesson."""

    DEFAULT_CSS = """
    LessonDetailView {
        width: 100%;
        height: 1fr;
        padding: 1 2;
        background: $surface-darken-1;
        border: solid $accent;
    }

    #detail-header {
        margin-bottom: 1;
        height: auto;
    }

    #meta-chips {
        margin-bottom: 1;
        height: auto;
    }

    .section-title {
        color: $accent;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }

    #rule-box {
        margin: 0 0 1 0;
        height: auto;
    }

    #critique-box {
        margin: 0 0 1 0;
        height: auto;
    }

    #linter-box {
        margin: 0 0 1 0;
        height: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lesson: Optional[Dict[str, Any]] = None
        self.is_pending: bool = True

    def compose(self) -> ComposeResult:
        yield Static("Select a lesson from the list to view details.", id="detail-header")
        yield Static("", id="meta-chips")
        yield Label("📜 Lesson Rule:", classes="section-title")
        yield Static("", id="rule-box")
        yield Label("🔍 Reviewer Critique / Trigger Diagnostics:", classes="section-title", id="critique-title")
        yield Static("", id="critique-box")
        yield Label("🛡️ Safety & Invariant Linter Analysis:", classes="section-title")
        yield Static("", id="linter-box")

    def display_lesson(self, lesson: Optional[Dict[str, Any]], is_pending: bool = True) -> None:
        """Update the view with details of the selected lesson."""
        self.lesson = lesson
        self.is_pending = is_pending

        header_widget = self.query_one("#detail-header", Static)
        meta_widget = self.query_one("#meta-chips", Static)
        rule_widget = self.query_one("#rule-box", Static)
        critique_title = self.query_one("#critique-title", Label)
        critique_widget = self.query_one("#critique-box", Static)
        linter_widget = self.query_one("#linter-box", Static)

        if not lesson:
            header_widget.update("No lesson selected.")
            meta_widget.update("")
            rule_widget.update("")
            critique_widget.update("")
            linter_widget.update("")
            return

        lid = lesson.get("id") or lesson.get("lesson_id") or "unknown"
        cat = lesson.get("category", "General")
        rule = lesson.get("rule") or lesson.get("proposed_rule") or ""
        ltype = lesson.get("lesson_type", "solved_pattern")
        outcome = lesson.get("outcome", "unknown")
        task_file = lesson.get("task_file") or lesson.get("source_task") or "N/A"
        staged_at = lesson.get("staged_at") or lesson.get("created") or "unknown"
        keywords = lesson.get("keywords", [])
        kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)

        # Header Title
        header_text = Text()
        header_text.append(f"📌 {lid} ", style="bold yellow")
        mode_str = "[PENDING REVIEW]" if is_pending else "[ACTIVE KNOWLEDGE]"
        mode_style = "bold magenta" if is_pending else "bold green"
        header_text.append(mode_str, style=mode_style)
        header_widget.update(header_text)

        # Meta Chips
        meta_text = Text()
        meta_text.append(f"Category: ", style="bold")
        meta_text.append(f"{cat}  |  ", style="cyan")
        meta_text.append(f"Type: ", style="bold")
        meta_text.append(f"{ltype}  |  ", style="green" if ltype == "solved_pattern" else "red")
        meta_text.append(f"Outcome: ", style="bold")
        meta_text.append(f"{outcome}  |  ", style="blue")
        meta_text.append(f"Staged/Created: ", style="bold")
        meta_text.append(f"{staged_at}\n", style="dim")
        meta_text.append(f"Source Task: ", style="bold")
        meta_text.append(f"{task_file}\n", style="dim cyan")
        meta_text.append(f"Keywords: ", style="bold")
        meta_text.append(f"[{kw_str}]", style="dim yellow")

        # Telemetry if active lesson
        if not is_pending:
            retrievals = lesson.get("retrieval_count", 0)
            prevented = lesson.get("prevented_rework_count", 0)
            utility = lesson.get("utility_score", 0.0)
            meta_text.append(
                f"\nTelemetry: Retrievals={retrievals} | Prevented Rework={prevented} | Utility={utility:.2f}",
                style="bold magenta",
            )

        meta_widget.update(meta_text)

        # Rule Box
        rule_panel = Panel(
            rule if rule else "[dim italic]No rule content defined[/dim italic]",
            title="[bold green]Promoted Invariant Rule[/bold green]",
            border_style="green" if not is_pending else "yellow",
        )
        rule_widget.update(rule_panel)

        # Critique / Diagnostic Box
        critique = lesson.get("reviewer_critique") or lesson.get("reason") or "No critique recorded."
        critique_title.update("🔍 Reviewer Critique / Trigger Diagnostics:" if is_pending else "🔍 Context / Reason:")
        critique_panel = Panel(
            critique,
            border_style="blue",
        )
        critique_widget.update(critique_panel)

        # Invariant Linter Analysis
        violations = lint_lesson({"id": lid, "rule": rule})
        if not violations:
            linter_panel = Panel(
                "✅ Compliant with all workspace contracts & safety suites:\n"
                "• TOOL_CONTRACT: Proper use of authorized pipeline tools\n"
                "• ANTI_SAFEGUARD: Preserves error flags & traps (set -euo pipefail, ERR traps)\n"
                "• TEST_SUBVERSION: Rigorous testing standards maintained\n"
                "• DESTRUCTIVE_COMMAND: Safe operational boundaries\n"
                "• ENVIRONMENT: Deterministic path & virtualenv isolation",
                title="[bold green]Invariant Linter: PASSED[/bold green]",
                border_style="green",
            )
        else:
            v_lines = [f"🚨 [CRITICAL/WARNING] Found {len(violations)} violation(s):"]
            for v in violations:
                icon = "❌" if v.severity == "CRITICAL" else "⚠️ "
                v_lines.append(f"{icon} [{v.suite} / {v.rule_name}]: {v.message}")
                v_lines.append(f"   Matched: \"{v.matched_text}\"")
            linter_panel = Panel(
                "\n".join(v_lines),
                title=f"[bold red]Invariant Linter: {len(violations)} VIOLATIONS[/bold red]",
                border_style="red",
            )
        linter_widget.update(linter_panel)
