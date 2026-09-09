"""Unit tests for run_pipeline and process_prompt MCP server tools."""

import json
from unittest.mock import patch

from mcp_ollama.server import process_jsonrpc, handle_run_pipeline


def test_mcp_tools_list_includes_pipeline_tools():
    """Verify tools/list exposes run_pipeline and process_prompt."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }
    resp = process_jsonrpc(req)
    assert resp is not None
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "run_pipeline" in tool_names
    assert "process_prompt" in tool_names


def test_mcp_tools_call_run_pipeline(tmp_path):
    """Verify tools/call run_pipeline dispatches and returns pipeline result."""
    prompt_file = tmp_path / "test_prompt.md"
    prompt_file.write_text("# Test Prompt\nDo something defensive.\n", encoding="utf-8")

    mock_result = {
        "run_id": "test-run-mcp-01",
        "status": "complete",
        "current_phase": "complete",
        "tasks": {"t-001": {"status": "success"}}
    }

    with patch("pipeline.run_pipeline", return_value=mock_result) as mock_run:
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "prompt": str(prompt_file),
                    "model": "winter-prime:latest"
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert "result" in resp
        content = resp["result"]["content"][0]["text"]
        parsed = json.loads(content)
        assert parsed["run_id"] == "test-run-mcp-01"
        assert parsed["status"] == "complete"
        assert mock_run.called


def test_mcp_tools_call_process_prompt_alias(tmp_path):
    """Verify tools/call process_prompt alias functions identically."""
    mock_result = {
        "run_id": "test-run-mcp-02",
        "status": "complete"
    }

    with patch("pipeline.run_pipeline", return_value=mock_result) as mock_run:
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "process_prompt",
                "arguments": {
                    "prompt": "Create defensive hello world",
                    "model": "winter-prime:latest"
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        content = resp["result"]["content"][0]["text"]
        parsed = json.loads(content)
        assert parsed["run_id"] == "test-run-mcp-02"
        assert mock_run.called


def test_mcp_run_pipeline_help_interception():
    """Verify run_pipeline with --help returns help text and does not execute pipeline."""
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "run_pipeline",
            "arguments": {
                "prompt": "--help"
            }
        }
    }
    with patch("pipeline.run_pipeline") as mock_run:
        resp = process_jsonrpc(req)
        assert resp is not None
        assert "result" in resp
        content = resp["result"]["content"][0]["text"]
        assert "Arc-Orc-Rev Multi-Agent Pipeline Runner" in content
        assert "winter-prime:latest" in content
        assert not mock_run.called


def test_mcp_run_pipeline_empty_prompt_validation():
    """Verify run_pipeline with empty prompt returns clear error and does not execute pipeline."""
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "run_pipeline",
            "arguments": {
                "prompt": "   "
            }
        }
    }
    with patch("pipeline.run_pipeline") as mock_run:
        resp = process_jsonrpc(req)
        assert resp is not None
        assert resp["result"].get("isError") is True
        content = resp["result"]["content"][0]["text"]
        assert "A non-empty 'prompt'" in content
        assert not mock_run.called


def test_mcp_run_pipeline_default_model():
    """Verify run_pipeline defaults to winter-prime:latest when model is not provided."""
    mock_result = {"run_id": "test-default-model", "status": "complete"}
    with patch("pipeline.run_pipeline", return_value=mock_result) as mock_run:
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "prompt": "Valid task prompt"
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert not resp["result"].get("isError")
        mock_run.assert_called_once_with("Valid task prompt", model="winter-prime:latest")

