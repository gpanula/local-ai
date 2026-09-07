"""State container for PipelineWatch TUI.

Consumes events from live event streams or trajectory replay, maintaining
reactive state for all widgets across iterations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


STAGE_ORDER = ["orchestrate", "author", "lint", "review", "execute"]


class IterationState:
    """State for a single iteration cycle."""

    def __init__(self, iteration_num: int):
        self.iteration = iteration_num
        self.context_window: Dict[str, Any] = {}
        self.thinking: str = ""
        self.stage_thinking: Dict[str, str] = {
            "orchestrate": "",
            "author": "",
            "lint": "",
            "review": "",
            "execute": "",
        }
        self.stage_models: Dict[str, str] = {
            "orchestrate": "",
            "author": "",
            "lint": "shellcheck",
            "review": "",
            "execute": "sandbox",
        }
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
        self.selected_stage: str = "author"
        self.active_iteration_idx: int = 1
        self.iterations: Dict[int, IterationState] = {}
        self.terminal_lines: List[str] = []
        self.outcome: str = "in_progress"
        self.abort_reason: str = ""
        self.duration_sec: float = 0.0
        self.elapsed_sec: float = 0.0

    def prev_stage(self) -> str:
        """Step left to previous stage in STAGE_ORDER."""
        idx = STAGE_ORDER.index(self.selected_stage) if self.selected_stage in STAGE_ORDER else 1
        new_idx = max(0, idx - 1)
        self.selected_stage = STAGE_ORDER[new_idx]
        return self.selected_stage

    def next_stage(self) -> str:
        """Step right to next stage in STAGE_ORDER."""
        idx = STAGE_ORDER.index(self.selected_stage) if self.selected_stage in STAGE_ORDER else 1
        new_idx = min(len(STAGE_ORDER) - 1, idx + 1)
        self.selected_stage = STAGE_ORDER[new_idx]
        return self.selected_stage

    def get_iteration(self, num: int) -> IterationState:
        if num not in self.iterations:
            self.iterations[num] = IterationState(num)
        return self.iterations[num]

    def current_iteration(self) -> IterationState:
        return self.get_iteration(self.active_iteration_idx)

    def get_stage_model(self, stage: str) -> str:
        """Resolve the model or tool name associated with a stage."""
        cur_it = self.current_iteration()
        m = cur_it.stage_models.get(stage)
        if m:
            return m
        if stage == "orchestrate":
            return self.models.get("orchestrator") or self.models.get("author", "")
        elif stage == "author":
            return self.models.get("author") or self.models.get("coder", "")
        elif stage == "lint":
            return "shellcheck"
        elif stage == "review":
            return self.models.get("reviewer") or self.models.get("author", "")
        elif stage == "execute":
            return "sandbox"
        return ""

    def get_stage_thinking(self, stage: str) -> str:
        """Retrieve deliberation or raw CoT for a specific stage."""
        cur_it = self.current_iteration()
        t = cur_it.stage_thinking.get(stage, "")
        if t:
            return t
        if stage == "author":
            return cur_it.thinking
        elif stage == "lint" and cur_it.linter:
            out = cur_it.linter.get("output", "")
            return f"Pre-Flight Linter (ShellCheck) Findings:\n{out}"
        elif stage == "review" and cur_it.review:
            v = cur_it.review.get("verdict", "")
            c = cur_it.review.get("critique", "")
            return f"Reviewer Gate Evaluation:\nVerdict: {v}\n\nCritique:\n{c}"
        elif stage == "execute" and self.terminal_lines:
            return "\n".join(self.terminal_lines[-50:])
        return ""

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
            st = data.get("stage", self.current_stage)
            self.current_stage = st
            if st in STAGE_ORDER:
                self.selected_stage = st
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
            st = data.get("stage") or self.current_stage
            if st not in STAGE_ORDER:
                st = "author"
            if chunk:
                if it.stage_thinking.get(st):
                    it.stage_thinking[st] += f"\n{chunk}"
                else:
                    it.stage_thinking[st] = chunk
                it.stage_models[st] = data.get("model", "")
                if it.thinking:
                    it.thinking += f"\n{chunk}"
                else:
                    it.thinking = chunk

        elif etype == "reasoning_chunk":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.reasoning.update(data.get("reasoning", {}))
            it.stage_models["author"] = data.get("model", "")

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
            out = data.get("output", "")
            it.stage_thinking["lint"] = f"Pre-Flight Linter (ShellCheck) Findings:\n{out}"
            it.stage_models["lint"] = "shellcheck"

        elif etype == "review_result":
            iter_num = data.get("iteration", self.active_iteration_idx)
            it = self.get_iteration(iter_num)
            it.review = data
            v = data.get("verdict", "")
            c = data.get("critique", "")
            it.stage_thinking["review"] = f"Reviewer Gate Evaluation:\nVerdict: {v}\n\nCritique:\n{c}"
            it.stage_models["review"] = data.get("reviewer_model") or self.models.get("reviewer", "")

        elif etype == "terminal_chunk":
            text = data.get("text", "")
            if text:
                self.terminal_lines.append(text)
                cur_it = self.current_iteration()
                if cur_it.stage_thinking.get("execute"):
                    cur_it.stage_thinking["execute"] += f"\n{text}"
                else:
                    cur_it.stage_thinking["execute"] = text

        elif etype == "pipeline_end":
            self.outcome = data.get("outcome", "unknown")
            self.duration_sec = data.get("duration_sec", 0.0)
            self.abort_reason = data.get("abort_reason", "")
            self.current_stage = "finished"
