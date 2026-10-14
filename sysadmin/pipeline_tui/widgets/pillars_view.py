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
        height: 13;
        min-height: 8;
        border: round $secondary;
        background: $background;
        padding: 0 1;
    }
    CognitivePillarsView:focus-within {
        border: double $accent;
    }
    .pillar-scroll {
        height: 1fr;
        scrollbar-size-vertical: 1;
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

    def update_state(self, iteration_state, prev_code: str = "", selected_stage: str = "author") -> None:
        from pipeline_tui.state import normalize_stage

        norm_st = normalize_stage(selected_stage)
        stage_r = iteration_state.stage_reasoning.get(norm_st) or iteration_state.stage_reasoning.get(selected_stage) or {}
        roles = iteration_state.review.get("roles") or {}
        role_info = roles.get(norm_st) or roles.get(selected_stage) or {}
        gen_r = iteration_state.reasoning or {}

        # Resolve model name
        model = iteration_state.stage_models.get(norm_st) or role_info.get("model", "")
        model_str = f" ({model})" if model else ""

        # Strategy
        strat = (
            stage_r.get("strategy")
            or stage_r.get("analysis")
            or role_info.get("strategy")
            or role_info.get("analysis")
            or gen_r.get("strategy")
            or gen_r.get("analysis")
        )
        if strat:
            strat = f"─── {norm_st.upper()} Strategy & Analysis{model_str} ───\n\n{strat}"
        else:
            strat = "No explicit strategy extracted."

        # Risks
        risks = (
            stage_r.get("risks")
            or role_info.get("risks")
            or gen_r.get("risks")
        )
        if risks:
            risks = f"─── {norm_st.upper()} Risks & Edge Cases ───\n\n{risks}"
        else:
            risks = "No explicit risks extracted."

        # Verification & Plan / Solution
        sol = (
            stage_r.get("solution")
            or stage_r.get("plan")
            or role_info.get("solution")
            or role_info.get("plan")
            or gen_r.get("solution")
            or ""
        )
        verif = (
            stage_r.get("verification_plan")
            or stage_r.get("verification")
            or role_info.get("verification_plan")
            or role_info.get("verification")
            or gen_r.get("verification_plan")
            or gen_r.get("verification")
        )
        if verif:
            verif_body = f"Plan / Decisions:\n{sol}\n\nVerification:\n{verif}" if sol else verif
            verif = f"─── {norm_st.upper()} Verification Plan ───\n\n{verif_body}"
        elif sol:
            verif = f"─── {norm_st.upper()} Plan / Decisions ───\n\n{sol}"
        else:
            verif = "No explicit verification plan extracted."

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

        # Automatically bring up the corresponding pillar tab for the active stage
        target_tab = "tab-strategy"
        if selected_stage in ("architect", "orchestrate", "orchestrator"):
            target_tab = "tab-strategy"
        elif selected_stage in ("coder", "sysadmin", "author", "dispatch", "execute"):
            target_tab = "tab-code"
        elif selected_stage in ("lint", "review", "reviewer"):
            target_tab = "tab-critique"
        elif selected_stage == "security":
            target_tab = "tab-risks"

        try:
            tabs = self.query_one("#pillars-tabs", TabbedContent)
            tabs.active = target_tab
        except Exception:
            pass
