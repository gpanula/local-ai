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


def test_mcp_run_pipeline_dual_model():
    """Verify run_pipeline with dual_model=True sets builder and auditor models."""
    mock_result = {"run_id": "test-dual-model", "status": "complete"}
    with patch("pipeline.run_pipeline", return_value=mock_result) as mock_run:
        req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "prompt": "Valid task prompt",
                    "dual_model": True
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert not resp["result"].get("isError")
        mock_run.assert_called_once_with("Valid task prompt", model="winter-prime:16gb", auditor_model="qwen3:8b")


def test_mcp_run_pipeline_dynamic_auditor():
    """Verify run_pipeline with dynamic_auditor=True sets dynamic_auditor flag and 16gb builder."""
    mock_result = {"run_id": "test-dynamic-auditor", "status": "complete"}
    with patch("pipeline.run_pipeline", return_value=mock_result) as mock_run:
        req = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "prompt": "Valid task prompt",
                    "dynamic_auditor": True
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert not resp["result"].get("isError")
        mock_run.assert_called_once_with("Valid task prompt", model="winter-prime:16gb", dynamic_auditor=True)


def test_mcp_tool_runtime_error_transparency():
    """Verify runtime errors propagate specific diagnostic error messages instead of generic internal errors."""
    with patch("pipeline.run_pipeline", side_effect=RuntimeError("Dispatch aborted: Task t-002 execution failed")):
        req = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "prompt": "Failing task prompt"
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert resp["result"].get("isError") is True
        content = resp["result"]["content"][0]["text"]
        assert "Error executing run_pipeline: Dispatch aborted: Task t-002 execution failed" in content


def test_mcp_tools_list_schema_retry_budget():
    """Verify tools/list exposes retry_budget for run_pipeline and process_prompt."""
    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/list",
        "params": {}
    }
    resp = process_jsonrpc(req)
    assert resp is not None
    tools = {t["name"]: t for t in resp["result"]["tools"]}
    assert "retry_budget" in tools["run_pipeline"]["inputSchema"]["properties"]
    assert tools["run_pipeline"]["inputSchema"]["properties"]["retry_budget"]["type"] == "integer"
    assert "retry_budget" in tools["process_prompt"]["inputSchema"]["properties"]
    assert tools["process_prompt"]["inputSchema"]["properties"]["retry_budget"]["type"] == "integer"


def test_mcp_run_pipeline_with_retry_budget():
    """Verify run_pipeline passes retry_budget integer to pipeline.run_pipeline."""
    mock_result = {"run_id": "test-retry-budget", "status": "complete"}
    with patch("pipeline.run_pipeline", return_value=mock_result) as mock_run:
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "prompt": "Valid task prompt",
                    "retry_budget": 5,
                    "dual_model": True,
                    "dynamic_auditor": True
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert not resp["result"].get("isError")
        mock_run.assert_called_once_with(
            "Valid task prompt",
            model="winter-prime:16gb",
            dynamic_auditor=True,
            retry_budget=5
        )


def test_mcp_run_pipeline_resume_only():
    """Verify run_pipeline with resume only calls resume_pipeline."""
    mock_result = {"run_id": "run-resume-123", "status": "resumed"}
    with patch("pipeline.resume_pipeline", return_value=mock_result) as mock_resume:
        req = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "resume": "run-resume-123"
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert not resp["result"].get("isError")
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["run_id"] == "run-resume-123"
        mock_resume.assert_called_once_with("run-resume-123", model="winter-prime:latest")


def test_mcp_run_pipeline_keep_models():
    """Verify run_pipeline with keep_models=True forwards keep_models to pipeline runner."""
    mock_result = {"run_id": "test-keep-models", "status": "complete"}
    with patch("pipeline.run_pipeline", return_value=mock_result) as mock_run:
        req = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "run_pipeline",
                "arguments": {
                    "prompt": "Test keep models prompt",
                    "keep_models": True,
                    "dual_model": True
                }
            }
        }
        resp = process_jsonrpc(req)
        assert resp is not None
        assert not resp["result"].get("isError")
        mock_run.assert_called_once_with(
            "Test keep models prompt",
            model="winter-prime:16gb",
            auditor_model="qwen3:8b",
            keep_models=True
        )


def test_mcp_run_pipeline_help_parameter():
    """Verify run_pipeline with help=True or help='all' returns full self-documenting help."""
    req = {
        "jsonrpc": "2.0",
        "id": 14,
        "method": "tools/call",
        "params": {
            "name": "run_pipeline",
            "arguments": {
                "help": True
            }
        }
    }
    with patch("pipeline.run_pipeline") as mock_run:
        resp = process_jsonrpc(req)
        assert resp is not None
        assert "result" in resp
        content = resp["result"]["content"][0]["text"]
        assert "Arc-Orc-Rev Multi-Agent Pipeline Runner" in content
        assert "Parameter: `keep_models`" in content
        assert "Parameter: `dual_model`" in content
        assert "Parameter: `dynamic_auditor`" in content
        assert not mock_run.called


def test_mcp_run_pipeline_help_specific_param():
    """Verify run_pipeline with help='<param>' returns specific verbose documentation."""
    req = {
        "jsonrpc": "2.0",
        "id": 15,
        "method": "tools/call",
        "params": {
            "name": "run_pipeline",
            "arguments": {
                "help": "keep_models"
            }
        }
    }
    with patch("pipeline.run_pipeline") as mock_run:
        resp = process_jsonrpc(req)
        assert resp is not None
        assert "result" in resp
        content = resp["result"]["content"][0]["text"]
        assert "### Parameter: `keep_models`" in content
        assert "GPU VRAM" in content
        assert not mock_run.called

