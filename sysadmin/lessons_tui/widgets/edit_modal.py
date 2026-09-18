"""Modal screen for editing a pending lesson before promotion."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from mcp_core.lesson_linter import lint_lesson


class EditLessonModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen allowing the developer to edit category, rule, and keywords."""

    DEFAULT_CSS = """
    EditLessonModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #modal-container {
        width: 80;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #modal-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    .field-label {
        color: $text-muted;
        margin-top: 1;
        text-style: bold;
    }

    #rule-input {
        height: 6;
        margin-bottom: 1;
    }

    #lint-status {
        margin: 1 0;
        padding: 0 1;
        height: auto;
    }

    .lint-clean {
        color: $success;
        text-style: bold;
    }

    .lint-violating {
        color: $error;
        text-style: bold;
    }

    #buttons-bar {
        margin-top: 1;
        align-horizontal: right;
        height: auto;
    }

    #btn-cancel {
        margin-right: 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save & Promote"),
    ]

    def __init__(self, lesson: Dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        self.lesson = lesson
        self.lesson_id = lesson.get("id") or lesson.get("lesson_id") or "unknown"
        self.initial_category = lesson.get("category", "")
        self.initial_rule = lesson.get("rule") or lesson.get("proposed_rule") or ""
        keywords = lesson.get("keywords", [])
        if isinstance(keywords, list):
            self.initial_keywords = ", ".join(keywords)
        else:
            self.initial_keywords = str(keywords)

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Label(f"✏️ Modify Pending Lesson: {self.lesson_id}", id="modal-title")

            yield Label("Category:", classes="field-label")
            yield Input(value=self.initial_category, id="cat-input", placeholder="e.g. Defensive Bash Scripting")

            yield Label("Rule Content:", classes="field-label")
            yield TextArea(self.initial_rule, id="rule-input")

            yield Label("Keywords (comma-separated):", classes="field-label")
            yield Input(value=self.initial_keywords, id="kw-input", placeholder="e.g. quoting, SC2086, bash")

            yield Static("", id="lint-status")

            with Horizontal(id="buttons-bar"):
                yield Button("Cancel [Esc]", variant="default", id="btn-cancel")
                yield Button("Save & Keep [Ctrl+S]", variant="primary", id="btn-save")

    def on_mount(self) -> None:
        self._update_lint_preview(self.initial_rule)

    @on(TextArea.Changed, "#rule-input")
    def on_rule_changed(self, event: TextArea.Changed) -> None:
        self._update_lint_preview(event.text_area.text)

    def _update_lint_preview(self, rule_text: str) -> None:
        lint_box = self.query_one("#lint-status", Static)
        violations = lint_lesson({"id": self.lesson_id, "rule": rule_text})
        if not violations:
            lint_box.update("✅ [Linter] Compliant with all workspace contracts & safety suites.")
            lint_box.set_classes("lint-clean")
        else:
            lines = [f"🚨 [Linter Warning] {len(violations)} violation(s) detected:"]
            for v in violations:
                lines.append(f"  • [{v.suite}/{v.rule_name}]: {v.message}")
            lint_box.update("\n".join(lines))
            lint_box.set_classes("lint-violating")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._submit()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel_pressed(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save")
    def on_save_pressed(self) -> None:
        self._submit()

    def _submit(self) -> None:
        cat = self.query_one("#cat-input", Input).value.strip()
        rule = self.query_one("#rule-input", TextArea).text.strip()
        kw_raw = self.query_one("#kw-input", Input).value.strip()
        kws = [k.strip() for k in kw_raw.split(",") if k.strip()]

        result = {
            "category": cat or self.initial_category,
            "rule": rule or self.initial_rule,
            "keywords": kws,
        }
        self.dismiss(result)
