"""Cognitive Pillars & Synthesized Artifacts widget."""

from __future__ import annotations

import difflib
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static, TabbedContent, TabPane


class CognitivePillarsView(Widget):
    """Tabbed view for the structured 4-pillar contract, synthesized code, and review critique."""

    DEFAULT_CSS = """
    CognitivePillarsView {
        height: 1fr;
        min-height: 12;
        border: round $secondary;
        background: $background;
        padding: 0 1;
    }
    .pillar-scroll {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent(id="pillars-tabs"):
            with TabPane("1. Strategy", id="tab-strategy"):
                with VerticalScroll(classes="pillar-scroll"):
                    yield Static("No strategy generated yet.", id="strategy-content")

            with TabPane("2. Risks & Edge Cases", id="tab-risks"):
                with VerticalScroll(classes="pillar-scroll"):
                    yield Static("No risk evaluation recorded.", id="risks-content")

            with TabPane("3. Synthesized Code", id="tab-code"):
                with VerticalScroll(classes="pillar-scroll"):
                    yield Static("No script synthesized yet.", id="code-content")

            with TabPane("4. Verification Plan", id="tab-verif"):
                with VerticalScroll(classes="pillar-scroll"):
                    yield Static("No verification plan generated.", id="verif-content")

            with TabPane("5. Critique & Lint", id="tab-critique"):
                with VerticalScroll(classes="pillar-scroll"):
                    yield Static("No reviewer critique or linter findings.", id="critique-content")

    def update_state(self, iteration_state, prev_code: str = "") -> None:
        reasoning = iteration_state.reasoning or {}
        strat = reasoning.get("strategy") or "No explicit strategy extracted."
        risks = reasoning.get("risks") or "No explicit risks extracted."
        verif = reasoning.get("verification_plan") or "No explicit verification plan extracted."
        code = iteration_state.code or ""

        # Strategy
        try:
            self.query_one("#strategy-content", Static).update(strat)
        except Exception:
            pass

        # Risks
        try:
            self.query_one("#risks-content", Static).update(risks)
        except Exception:
            pass

        # Verification
        try:
            self.query_one("#verif-content", Static).update(verif)
        except Exception:
            pass

        # Code & Diff
        try:
            code_widget = self.query_one("#code-content", Static)
            if code:
                if prev_code and prev_code != code:
                    # Render unified diff
                    diff_lines = list(difflib.unified_diff(
                        prev_code.splitlines(),
                        code.splitlines(),
                        fromfile="Iteration N-1 (Rejected)",
                        tofile=f"Iteration {iteration_state.iteration} (Revised)",
                        lineterm="",
                    ))
                    diff_text = "\n".join(diff_lines)
                    code_widget.update(Syntax(diff_text, "diff", theme="monokai", line_numbers=True))
                else:
                    code_widget.update(Syntax(code, "bash", theme="monokai", line_numbers=True))
            else:
                code_widget.update("No code block synthesized.")
        except Exception:
            pass

        # Critique & Lint
        try:
            critique_widget = self.query_one("#critique-content", Static)
            crit_text = Text()

            linter = iteration_state.linter
            if linter:
                passed = linter.get("passed", False)
                out = linter.get("output", "")
                crit_text.append("─── Pre-Flight Linter (ShellCheck) ────────────────\n", style="bold cyan")
                crit_text.append(f"Status: {'PASSED (exit 0)' if passed else 'FAILED'}\n", style="green" if passed else "bold red")
                crit_text.append(f"{out}\n\n")

            review = iteration_state.review
            if review:
                verdict = review.get("verdict", "")
                critique = review.get("critique", "")
                model = review.get("reviewer_model", "")
                crit_text.append(f"─── Reviewer Evaluation ({model}) ───────────────\n", style="bold magenta")
                verdict_style = "bold green" if "APPROV" in verdict else "bold red"
                crit_text.append(f"Verdict: {verdict}\n", style=verdict_style)
                crit_text.append(f"{critique}\n")

            if not linter and not review:
                crit_text.append("Awaiting linter and reviewer stages...")

            critique_widget.update(crit_text)
        except Exception:
            pass
