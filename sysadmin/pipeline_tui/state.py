"""State container for PipelineWatch TUI.

Consumes events from live event streams or trajectory replay, maintaining
reactive state for all widgets across iterations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class IterationState:
    """State for a single iteration cycle."""

    def __init__(self, iteration_num: int):
        self.iteration = iteration_num
        self.context_window: Dict[str, Any] = {}
        self.thinking: str = ""
        self.reasoning: Dict[str, Any] = {}
        self.code: str = ""
        self.script_name: Optional[str] = None
        self.stats: Dict[str, Any] = {}
        self.linter: Dict[str, Any] = {}
        self.review: Dict[str, Any] = {}


class PipelineState:
    """Complete state for a monitored pipeline run."""

    def __init__(self):
        self.run_id: str = ""
        self.start_time: str = ""
        self.task_file: str = ""
        self.prompt: str = ""
        self.tier: str = "8gb"
        self.models: Dict[str, str] = {}
        self.max_retries: int = 3
        self.current_stage: str = "idle"
        self.active_iteration_idx: int = 1
        self.iterations: Dict[int, IterationState] = {}
        self.terminal_lines: List[str] = []
        self.outcome: str = "in_progress"
        self.abort_reason: str = ""
        self.duration_sec: float = 0.0
        self.elapsed_sec: float = 0.0

    def get_iteration(self, num: int) -> IterationState:
        if num not in self.iterations:
            self.iterations[num] = IterationState(num)
        return self.iterations[num]

    def current_iteration(self) -> IterationState:
        return self.get_iteration(self.active_iteration_idx)

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Apply an incoming event dictionary to update state."""
        etype = event.get("type")
        data = event.get("data", {})
        self.run_id = event.get("run_id") or self.run_id

        if etype == "pipeline_start":
            self.task_file = data.get("task_file", "")
            self.prompt = data.get("prompt", "")
            self.tier = data.get("tier") or "8gb"
            self.models = data.get("models", {})
            self.max_retries = data.get("max_retries", 3)
            self.start_time = event.get("timestamp", "")
            self.current_stage = "start"

        elif etype == "stage_transition":
            self.current_stage = data.get("stage", self.current_stage)
            iter_num = data.get("iteration", 1)
            self.active_iteration_idx = iter_num
            self.get_iteration(iter_num)

        elif etype == "context_window":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.context_window = data

        elif etype == "thinking_chunk":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            chunk = data.get("chunk", "")
            if chunk:
                if it.thinking:
                    it.thinking += f"\n{chunk}"
                else:
                    it.thinking = chunk

        elif etype == "reasoning_chunk":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.reasoning.update(data.get("reasoning", {}))

        elif etype == "code_synthesized":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.code = data.get("code", "")
            it.script_name = data.get("script_name")
            it.stats = data.get("stats", {})

        elif etype == "linter_result":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.linter = data

        elif etype == "review_result":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.review = data

        elif etype == "terminal_chunk":
            text = data.get("text", "")
            if text:
                self.terminal_lines.append(text)

        elif etype == "pipeline_end":
            self.outcome = data.get("outcome", "unknown")
            self.duration_sec = data.get("duration_sec", 0.0)
            self.abort_reason = data.get("abort_reason", "")
            self.current_stage = "finished"
