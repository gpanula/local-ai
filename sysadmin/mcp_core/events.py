"""Structured event emitter for pipeline observability and TUI watching.

Writes JSONL event streams to `.localai/runs/<run_id>.jsonl` and maintains
a `.localai/runs/latest.jsonl` symlink. Zero-risk: operations never block
or raise exceptions if file I/O fails.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from mcp_core.workspace import WORKSPACE_ROOT

logger = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = os.path.join(WORKSPACE_ROOT, ".localai", "runs")


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def generate_run_id() -> str:
    """Generate a unique run ID formatted with timestamp and uuid prefix."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rand_hex = uuid.uuid4().hex[:6]
    return f"run-{ts}-{rand_hex}"


class EventEmitter:
    """Thread-safe and exception-resilient event emitter for pipeline runs."""

    _instance: Optional[EventEmitter] = None

    def __init__(self, run_id: Optional[str] = None, runs_dir: Optional[str] = None):
        self.runs_dir = runs_dir or DEFAULT_RUNS_DIR
        self.run_id = run_id or generate_run_id()
        self.run_file = os.path.join(self.runs_dir, f"{self.run_id}.jsonl")
        self.latest_link = os.path.join(self.runs_dir, "latest.jsonl")
        self._initialized = False

    @classmethod
    def get_current(cls) -> Optional[EventEmitter]:
        """Return the current global active emitter, if one is registered."""
        return cls._instance

    @classmethod
    def set_current(cls, emitter: Optional[EventEmitter]) -> None:
        """Set or clear the global active emitter."""
        cls._instance = emitter

    def _ensure_init(self) -> bool:
        if self._initialized:
            return True
        try:
            os.makedirs(self.runs_dir, exist_ok=True)
            # Maintain latest.jsonl pointer (atomic symlink replacement)
            temp_link = os.path.join(self.runs_dir, f".latest.{uuid.uuid4().hex[:6]}.tmp")
            try:
                # Use relative target if possible
                rel_target = os.path.basename(self.run_file)
                os.symlink(rel_target, temp_link)
                os.replace(temp_link, self.latest_link)
            except Exception:
                # Symlinks might fail on certain filesystems; fallback to copy or touch
                try:
                    if os.path.lexists(temp_link):
                        os.remove(temp_link)
                except Exception:
                    pass
            self._initialized = True
            return True
        except Exception as exc:
            logger.warning("Failed to initialize run directory '%s': %s", self.runs_dir, exc)
            return False

    def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Emit a structured event. Never raises an exception."""
        payload = {
            "run_id": self.run_id,
            "timestamp": _now_iso(),
            "type": event_type,
            "data": data or {},
        }
        try:
            if not self._ensure_init():
                return
            line = json.dumps(payload, ensure_ascii=False)
            with open(self.run_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as exc:
            logger.warning("EventEmitter.emit failed for event '%s': %s", event_type, exc)

    # --- Domain-specific convenience helpers ---

    def pipeline_start(self, task_file: str, prompt: str, tier: Optional[str], models: Dict[str, str], max_retries: int) -> None:
        self.emit("pipeline_start", {
            "task_file": task_file,
            "prompt": prompt,
            "tier": tier,
            "models": models,
            "max_retries": max_retries,
        })

    def stage_transition(self, stage: str, iteration: int = 1, metadata: Optional[Dict[str, Any]] = None) -> None:
        data = {"stage": stage, "iteration": iteration}
        if metadata:
            data.update(metadata)
        self.emit("stage_transition", data)

    def context_window(
        self,
        iteration: int,
        system_rules: str,
        tools: list[Any],
        lessons: list[Dict[str, Any]],
        user_prompt: str,
        rework_feedback: str = "",
        context_limit: int = 8192,
    ) -> None:
        """Emit the broken-down context window payload and token estimates."""
        # Simple heuristic: ~4 chars per token estimate
        def est_tokens(text: str) -> int:
            return max(1, len(text) // 4) if text else 0

        rules_tokens = est_tokens(system_rules)
        tools_str = json.dumps(tools, ensure_ascii=False) if tools else ""
        tools_tokens = est_tokens(tools_str)
        lessons_str = json.dumps(lessons, ensure_ascii=False) if lessons else ""
        lessons_tokens = est_tokens(lessons_str)
        prompt_tokens = est_tokens(user_prompt)
        feedback_tokens = est_tokens(rework_feedback)
        total_tokens = rules_tokens + tools_tokens + lessons_tokens + prompt_tokens + feedback_tokens

        self.emit("context_window", {
            "iteration": iteration,
            "system_rules": system_rules,
            "tools": tools,
            "lessons": lessons,
            "user_prompt": user_prompt,
            "rework_feedback": rework_feedback,
            "token_breakdown": {
                "rules": rules_tokens,
                "tools": tools_tokens,
                "lessons": lessons_tokens,
                "prompt": prompt_tokens,
                "feedback": feedback_tokens,
                "total": total_tokens,
                "limit": context_limit,
            },
        })

    def thinking_chunk(self, iteration: int, model: str, chunk: str, is_final: bool = False) -> None:
        self.emit("thinking_chunk", {
            "iteration": iteration,
            "model": model,
            "chunk": chunk,
            "is_final": is_final,
        })

    def reasoning_chunk(self, iteration: int, model: str, reasoning: Dict[str, Any]) -> None:
        self.emit("reasoning_chunk", {
            "iteration": iteration,
            "model": model,
            "reasoning": reasoning,
        })

    def code_synthesized(self, iteration: int, code: str, script_name: Optional[str] = None, stats: Optional[Dict[str, Any]] = None) -> None:
        self.emit("code_synthesized", {
            "iteration": iteration,
            "code": code,
            "script_name": script_name,
            "stats": stats or {},
        })

    def linter_result(self, iteration: int, passed: bool, output: str, returncode: int = 0) -> None:
        self.emit("linter_result", {
            "iteration": iteration,
            "passed": passed,
            "output": output,
            "returncode": returncode,
        })

    def review_result(self, iteration: int, verdict: str, critique: str, reviewer_model: str, roles: Optional[Dict[str, Any]] = None) -> None:
        self.emit("review_result", {
            "iteration": iteration,
            "verdict": verdict,
            "critique": critique,
            "reviewer_model": reviewer_model,
            "roles": roles or {},
        })

    def terminal_chunk(self, text: str, source: str = "terminal-mcp") -> None:
        self.emit("terminal_chunk", {
            "text": text,
            "source": source,
        })

    def pipeline_end(self, outcome: str, iterations: int, duration_sec: float = 0.0, trajectory_id: Optional[str] = None, abort_reason: str = "") -> None:
        self.emit("pipeline_end", {
            "outcome": outcome,
            "iterations": iterations,
            "duration_sec": duration_sec,
            "trajectory_id": trajectory_id,
            "abort_reason": abort_reason,
        })
