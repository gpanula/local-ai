"""Unit tests for mcp_core.extraction — lesson extraction helpers (mocked transport)."""

from mcp_core import transport
from mcp_core.extraction import (
    extract_lesson_from_critique,
    extract_lesson_from_stuck_loop,
)


# --- extract_lesson_from_critique ---

def test_critique_valid_json(monkeypatch):
    def _fake(tool_name, arguments):
        assert tool_name == "ollama_chat"
        # Constrained prompt must demand JSON-only output.
        assert "ONLY a valid JSON object" in arguments["system_prompt"]
        assert "no preamble" in arguments["system_prompt"]
        return (
            '{"category": "sysadmin_bash", "keywords": ["trap", "write_file"], '
            '"proposed_rule": "Never nest script content inside subshell strings."}'
        )

    monkeypatch.setattr(transport, "call_mcp", _fake)
    lesson = extract_lesson_from_critique(
        "Fix 1: script writes command as string.",
        "sysadmin/prompts/hello_world_test.md",
        "prompt ctx",
        "qwen3:8b",
        lesson_type="solved_pattern",
        outcome="approved",
    )
    assert lesson["category"] == "sysadmin_bash"
    assert lesson["keywords"] == ["trap", "write_file"]
    assert lesson["proposed_rule"] == "Never nest script content inside subshell strings."
    assert lesson["lesson_type"] == "solved_pattern"
    assert lesson["outcome"] == "approved"
    assert lesson["task_file"] == "sysadmin/prompts/hello_world_test.md"


def test_critique_garbage_fallback(monkeypatch):
    def _fake(tool_name, arguments):
        return "I am sorry, I cannot do that. Some prose about traps and heredocs."

    monkeypatch.setattr(transport, "call_mcp", _fake)
    lesson = extract_lesson_from_critique(
        "Fix the trap and heredoc delimiter issues.",
        "sysadmin/prompts/x.md",
        "ctx",
        "qwen3:8b",
        lesson_type="hard_failure",
        outcome="failed",
    )
    assert lesson["category"] == "unknown"
    assert lesson["lesson_type"] == "hard_failure"
    assert lesson["outcome"] == "failed"
    assert lesson["proposed_rule"] == "Fix the trap and heredoc delimiter issues."
    assert isinstance(lesson["keywords"], list) and len(lesson["keywords"]) > 0


def test_critique_transport_raises_fallback(monkeypatch):
    def _fake(tool_name, arguments):
        raise RuntimeError("server down")

    monkeypatch.setattr(transport, "call_mcp", _fake)
    lesson = extract_lesson_from_critique(
        "Fix quoting.", "sysadmin/prompts/y.md", "ctx", "qwen3:8b"
    )
    assert lesson["category"] == "unknown"
    assert lesson["proposed_rule"] == "Fix quoting."


# --- extract_lesson_from_stuck_loop ---

def test_stuck_loop_no_ollama_calls(monkeypatch):
    calls = []

    def _fake(tool_name, arguments):
        calls.append(tool_name)
        return "unused"

    monkeypatch.setattr(transport, "call_mcp", _fake)
    history = [
        ("- Fix heredoc delimiter indentation", "- Add set -euo pipefail"),
        ("- Fix heredoc delimiter indentation", "- Add set -euo pipefail"),
        ("- Fix heredoc delimiter indentation", "- Add set -euo pipefail"),
    ]
    lesson = extract_lesson_from_stuck_loop(
        history, "Stuck in reviewer revision loop on iteration 3/3", "sysadmin/prompts/h.md"
    )
    assert lesson["lesson_type"] == "intractable_pattern"
    assert lesson["outcome"] == "aborted"
    assert "heredoc" in lesson["proposed_rule"]
    assert "pipefail" in lesson["proposed_rule"]
    assert calls == [], f"call_mcp was invoked: {calls}"


def test_stuck_loop_empty_history_uses_abort_reason(monkeypatch):
    monkeypatch.setattr(transport, "call_mcp", lambda *a, **k: "unused")
    lesson = extract_lesson_from_stuck_loop([], "Stuck loop", "sysadmin/prompts/h.md")
    assert lesson["lesson_type"] == "intractable_pattern"
    assert lesson["outcome"] == "aborted"
    assert "Stuck loop" in lesson["proposed_rule"]
