"""Main Textual Application for PipelineWatch."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical

from mcp_core.workspace import WORKSPACE_ROOT
from pipeline_tui.discovery import find_run, list_runs, load_events_for_run
from pipeline_tui.state import PipelineState
from pipeline_tui.widgets.context_drawer import ContextWindowDrawer
from pipeline_tui.widgets.header import PipelineHeader
from pipeline_tui.widgets.pillars_view import CognitivePillarsView
from pipeline_tui.widgets.run_picker import RunPickerModal
from pipeline_tui.widgets.stepper import PipelineStepper
from pipeline_tui.widgets.terminal_drawer import TerminalConsoleDrawer
from pipeline_tui.widgets.thinking_view import ActiveThinkingView


class PipelineWatchApp(App):
    """Textual TUI for watching live pipeline execution and replaying past runs."""

    CSS = """
    Screen {
        background: $background;
    }
    #main-container {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "toggle_context", "Toggle Context"),
        Binding("t", "toggle_terminal", "Resize Console"),
        Binding("f", "snap_terminal", "Follow Console"),
        Binding("o", "open_picker", "Open Run"),
        Binding("r", "open_picker", "Open Run"),
        Binding("left_square_bracket", "prev_iteration", "Prev Iter"),
        Binding("right_square_bracket", "next_iteration", "Next Iter"),
    ]

    def __init__(
        self,
        target_run_id: Optional[str] = None,
        event_file: Optional[str] = None,
        is_replay: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.state = PipelineState()
        self.target_run_id = target_run_id
        self.event_file = event_file
        self.is_replay = is_replay
        self._tail_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        yield PipelineHeader(id="header")
        yield PipelineStepper(id="stepper")
        with Vertical(id="main-container"):
            yield ActiveThinkingView(id="thinking-view")
            yield CognitivePillarsView(id="pillars-view")
            yield ContextWindowDrawer(id="context-drawer")
            yield TerminalConsoleDrawer(id="terminal-drawer")

    async def on_mount(self) -> None:
        if self.is_replay:
            # Explicit replay mode
            target = self.target_run_id or "latest"
            run_match = find_run(target)
            if run_match:
                self._load_and_apply_run(run_match)
            else:
                self.action_open_picker()
        elif self.event_file and os.path.exists(self.event_file):
            # Watch specific event file
            self._tail_task = asyncio.create_task(self._tail_events(self.event_file))
        else:
            # Real-Time Live Watch Mode (Default for localai-tui / localai-watch)
            self._tail_task = asyncio.create_task(self._watch_live_runs())

    def _load_and_apply_run(self, run_info: Dict[str, Any]) -> None:
        """Load and apply all events from a selected run."""
        events = load_events_for_run(run_info)
        self.state = PipelineState()
        for evt in events:
            self.state.handle_event(evt)
        self._refresh_all_widgets()

    async def _watch_live_runs(self) -> None:
        """Watch for active and incoming pipeline runs in real-time."""
        runs_dir = os.path.join(WORKSPACE_ROOT, ".localai", "runs")
        latest_link = os.path.join(runs_dir, "latest.jsonl")
        current_target_file: Optional[str] = None
        last_finished_file: Optional[str] = None
        pos = 0

        # Check if an existing latest run is currently active
        is_active = False
        if os.path.exists(latest_link):
            resolved = os.path.realpath(latest_link)
            try:
                with open(resolved, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if lines and not any('"pipeline_end"' in line for line in lines):
                        is_active = True
                        current_target_file = resolved
                        for line in lines:
                            line = line.strip()
                            if line:
                                evt = json.loads(line)
                                self.state.handle_event(evt)
                        pos = f.tell()
                        self._refresh_all_widgets()
                    else:
                        last_finished_file = resolved
            except Exception:
                pass

        if not is_active:
            # Set waiting state
            self.state.run_id = "waiting"
            self.state.current_stage = "waiting for run"
            self.query_one("#header", PipelineHeader).update_state(self.state)
            self.query_one("#stepper", PipelineStepper).update_state(self.state)
            self.query_one("#thinking-view", ActiveThinkingView).update_thinking(
                "⏳ Observer ready. Watching for live pipeline executions in real-time...\n\n"
                "Run in another terminal:\n"
                "  localai-pipeline <prompt.md>\n"
                "or press 'o' / 'r' to browse and replay past runs."
            )

        while True:
            try:
                if os.path.exists(latest_link):
                    target_file = os.path.realpath(latest_link)

                    # Detect new run startup
                    if target_file != current_target_file and target_file != last_finished_file:
                        current_target_file = target_file
                        pos = 0
                        self.state = PipelineState()
                        self._refresh_all_widgets()

                    # Tail events from current run
                    if current_target_file and os.path.exists(current_target_file):
                        with open(current_target_file, "r", encoding="utf-8") as f:
                            f.seek(pos)
                            new_lines = f.readlines()
                            pos = f.tell()

                        for line in new_lines:
                            line = line.strip()
                            if line:
                                try:
                                    evt = json.loads(line)
                                    self.state.handle_event(evt)
                                    self._apply_single_event_ui(evt)
                                    if evt.get("type") == "pipeline_end":
                                        last_finished_file = current_target_file
                                except Exception:
                                    pass
            except Exception:
                pass
            await asyncio.sleep(0.2)

    async def _tail_events(self, file_path: str) -> None:
        """Tail JSONL events from active run file."""
        pos = 0
        while True:
            try:
                if os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        f.seek(pos)
                        lines = f.readlines()
                        pos = f.tell()

                    for line in lines:
                        line = line.strip()
                        if line:
                            try:
                                evt = json.loads(line)
                                self.state.handle_event(evt)
                                self._apply_single_event_ui(evt)
                            except Exception:
                                pass
            except Exception:
                pass
            await asyncio.sleep(0.2)

    def _apply_single_event_ui(self, evt: Dict[str, Any]) -> None:
        etype = evt.get("type")
        self.query_one("#header", PipelineHeader).update_state(self.state)
        self.query_one("#stepper", PipelineStepper).update_state(self.state)

        cur_it = self.state.current_iteration()
        if etype == "thinking_chunk":
            self.query_one("#thinking-view", ActiveThinkingView).update_thinking(cur_it.thinking)
        elif etype in ("reasoning_chunk", "code_synthesized", "linter_result", "review_result"):
            prev_it = self.state.iterations.get(cur_it.iteration - 1)
            prev_code = prev_it.code if prev_it else ""
            self.query_one("#pillars-view", CognitivePillarsView).update_state(cur_it, prev_code=prev_code)
        elif etype == "context_window":
            self.query_one("#context-drawer", ContextWindowDrawer).update_context(cur_it.context_window)
        elif etype == "terminal_chunk":
            text = evt.get("data", {}).get("text", "")
            self.query_one("#terminal-drawer", TerminalConsoleDrawer).append_line(text)

    def _refresh_all_widgets(self) -> None:
        """Full refresh of all UI components to reflect current state."""
        self.query_one("#header", PipelineHeader).update_state(self.state)
        self.query_one("#stepper", PipelineStepper).update_state(self.state)

        cur_it = self.state.current_iteration()
        self.query_one("#thinking-view", ActiveThinkingView).update_thinking(cur_it.thinking)

        prev_it = self.state.iterations.get(cur_it.iteration - 1)
        prev_code = prev_it.code if prev_it else ""
        self.query_one("#pillars-view", CognitivePillarsView).update_state(cur_it, prev_code=prev_code)
        self.query_one("#context-drawer", ContextWindowDrawer).update_context(cur_it.context_window)

        # Terminal lines
        term = self.query_one("#terminal-drawer", TerminalConsoleDrawer)
        for line in self.state.terminal_lines:
            term.append_line(line)

    # --- Actions ---

    def action_toggle_context(self) -> None:
        self.query_one("#context-drawer", ContextWindowDrawer).toggle()

    def action_toggle_terminal(self) -> None:
        self.query_one("#terminal-drawer", TerminalConsoleDrawer).toggle_size()

    def action_snap_terminal(self) -> None:
        self.query_one("#terminal-drawer", TerminalConsoleDrawer).snap_to_bottom()

    def action_prev_iteration(self) -> None:
        if self.state.active_iteration_idx > 1:
            self.state.active_iteration_idx -= 1
            self._refresh_all_widgets()

    def action_next_iteration(self) -> None:
        max_it = max(self.state.iterations.keys()) if self.state.iterations else 1
        if self.state.active_iteration_idx < max_it:
            self.state.active_iteration_idx += 1
            self._refresh_all_widgets()

    def action_open_picker(self) -> None:
        runs = list_runs(limit=100)

        def on_selected(run_info: Optional[Dict[str, Any]]) -> None:
            if run_info:
                self._load_and_apply_run(run_info)

        self.push_screen(RunPickerModal(runs), on_selected)
