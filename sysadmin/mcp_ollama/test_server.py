#!/usr/bin/env python3
"""
Unit and Integration Tests for Ollama MCP Server
"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server


class TestOllamaMCPServer(unittest.TestCase):

    def test_initialize(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertEqual(res["id"], 1)
        self.assertIn("capabilities", res["result"])
        self.assertEqual(res["result"]["serverInfo"]["name"], "local-ollama-mcp")

    def test_tools_list(self):
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("write_file", tool_names)
        self.assertIn("read_file", tool_names)
        self.assertIn("ollama_list_models", tool_names)
        self.assertIn("ollama_chat", tool_names)
        self.assertIn("ollama_task_agent", tool_names)
        self.assertIn("ollama_pull_model", tool_names)
        self.assertIn("ansible_syntax_check", tool_names)
        self.assertIn("shellcheck_inspect", tool_names)
        self.assertIn("service_status", tool_names)
        self.assertIn("journal_logs", tool_names)

    def test_write_and_read_file(self):
        test_rel_path = "sysadmin/scratch_test_file.txt"
        content_1 = "Line 1: Hello from MCP\nLine 2: Testing write_file\nLine 3: Third line\n"
        
        # 1. Write file
        req_write = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "write_file",
                "arguments": {
                    "path": test_rel_path,
                    "content": content_1,
                    "make_executable": True
                }
            }
        }
        res_write = server.process_jsonrpc(req_write)
        self.assertIsNotNone(res_write)
        self.assertNotIn("isError", res_write.get("result", {}))
        self.assertIn("Successfully wrote", res_write["result"]["content"][0]["text"])

        # Verify file exists on disk and is executable
        full_path = os.path.join(server.WORKSPACE_ROOT, test_rel_path)
        self.assertTrue(os.path.isfile(full_path))
        self.assertTrue(os.access(full_path, os.X_OK))

        # 2. Read full file
        req_read = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "read_file",
                "arguments": {"path": test_rel_path}
            }
        }
        res_read = server.process_jsonrpc(req_read)
        self.assertIsNotNone(res_read)
        self.assertIn("Line 1: Hello from MCP", res_read["result"]["content"][0]["text"])

        # 3. Read slice (lines 2 to 2)
        req_slice = {
            "jsonrpc": "2.0",
            "id": 102,
            "method": "tools/call",
            "params": {
                "name": "read_file",
                "arguments": {
                    "path": test_rel_path,
                    "start_line": 2,
                    "end_line": 2
                }
            }
        }
        res_slice = server.process_jsonrpc(req_slice)
        self.assertIn("Line 2: Testing write_file", res_slice["result"]["content"][0]["text"])
        self.assertNotIn("Line 1:", res_slice["result"]["content"][0]["text"])

        # 4. Append to file
        req_append = {
            "jsonrpc": "2.0",
            "id": 103,
            "method": "tools/call",
            "params": {
                "name": "write_file",
                "arguments": {
                    "path": test_rel_path,
                    "content": "Line 4: Appended\n",
                    "mode": "append"
                }
            }
        }
        res_append = server.process_jsonrpc(req_append)
        self.assertIn("Successfully wrote", res_append["result"]["content"][0]["text"])

        # Cleanup
        if os.path.exists(full_path):
            os.remove(full_path)

    def test_file_tools_path_traversal_rejected(self):
        # Write traversal
        with self.assertRaises(ValueError):
            server.handle_write_file("/etc/cron.d/malicious", "test")
        with self.assertRaises(ValueError):
            server.handle_write_file("../../etc/passwd", "test")

        # Read traversal
        with self.assertRaises(ValueError):
            server.handle_read_file("/etc/shadow")
        with self.assertRaises(ValueError):
            server.handle_read_file("../../etc/passwd")


    def test_ansible_syntax_check_valid(self):
        playbook = """
- name: Test Playbook
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Ping test
      ansible.builtin.debug:
        msg: "Hello World"
"""
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "ansible_syntax_check",
                "arguments": {"content": playbook}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        self.assertNotIn("isError", res["result"])
        text = res["result"]["content"][0]["text"]
        self.assertTrue("Passed" in text or "syntax OK" in text or "YAML validation passed" in text)
        print("\n[Ansible Valid Syntax Output]:\n", text)

    def test_ansible_syntax_check_invalid(self):
        invalid_yaml = """
- name: Broken
  hosts: localhost
    tasks:
  - invalid_indentation: [
"""
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "ansible_syntax_check",
                "arguments": {"content": invalid_yaml}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        text = res["result"]["content"][0]["text"]
        self.assertTrue(text.startswith("❌"))
        print("\n[Ansible Invalid Syntax Output]:\n", text)

    def test_shellcheck_inspect_clean(self):
        script = """#!/usr/bin/env bash
set -euo pipefail
msg="hello"
echo "${msg}"
"""
        req = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "shellcheck_inspect",
                "arguments": {"script": script}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        text = res["result"]["content"][0]["text"]
        self.assertTrue("No syntax or style issues detected" in text or "binary not found" in text)
        print("\n[ShellCheck Clean Output]:\n", text)

    def test_shellcheck_inspect_warning(self):
        script = """#!/usr/bin/env bash
echo $UNQUOTED_VAR
"""
        req = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "shellcheck_inspect",
                "arguments": {"script": script}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        text = res["result"]["content"][0]["text"]
        self.assertTrue(text.startswith("⚠️") or "SC2086" in text or "binary not found" in text)
        print("\n[ShellCheck Warning Output]:\n", text)

    def test_service_status(self):
        req = {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "service_status",
                "arguments": {"failed_only": True}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        text = res["result"]["content"][0]["text"]
        self.assertTrue(len(text) > 0)
        print("\n[Service Status Output]:\n", text)

    def test_journal_logs(self):
        req = {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "journal_logs",
                "arguments": {"lines": 5}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        text = res["result"]["content"][0]["text"]
        self.assertTrue(len(text) > 0)
        print("\n[Journal Logs Output]:\n", text)

    def test_live_list_models(self):
        """Integration test querying live local Ollama instance."""
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "ollama_list_models",
                "arguments": {}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        self.assertNotIn("isError", res["result"])
        content_text = res["result"]["content"][0]["text"]
        self.assertIn("qwen3:8b", content_text)
        print("\n[Live Ollama List Models Output]:\n", content_text)

    def test_live_chat(self):
        """Integration test querying qwen3:8b live on Ollama."""
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "ollama_chat",
                "arguments": {
                    "model": "qwen3:8b",
                    "prompt": "Reply with exactly: 'OLLAMA_MCP_ONLINE'",
                    "temperature": 0.0,
                    "num_ctx": 2048
                }
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        self.assertNotIn("isError", res["result"])
        content_text = res["result"]["content"][0]["text"]
        self.assertIn("OLLAMA_MCP_ONLINE", content_text)
        print("\n[Live Ollama Chat Output]:\n", content_text)

    def test_unknown_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "non_existent_tool",
                "arguments": {}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertTrue(res["result"].get("isError"))
        self.assertIn("Unknown tool", res["result"]["content"][0]["text"])

    def test_validate_ollama_host(self):
        self.assertEqual(server._validate_ollama_host("http://127.0.0.1:11434"), "http://127.0.0.1:11434")
        self.assertEqual(server._validate_ollama_host("http://localhost:11434/"), "http://localhost:11434")
        self.assertEqual(server._validate_ollama_host("http://192.168.1.50:11434"), "http://192.168.1.50:11434")
        
        with self.assertRaises(ValueError):
            server._validate_ollama_host("ftp://127.0.0.1:11434")
        with self.assertRaises(ValueError):
            server._validate_ollama_host("file:///etc/passwd")
        with self.assertRaises(ValueError):
            server._validate_ollama_host("http://evil-public-site.com:11434")

    def test_find_executable_path_traversal(self):
        # Path traversal with non-system binary should be rejected and return None
        res = server._find_executable("shadow", bin_dir="/etc")
        self.assertIsNone(res)

    def test_mcp_help_text_schema_parity(self):
        """
        Verify that parameters documented in --help text (e.g. run_pipeline)
        are present in the corresponding MCP inputSchema.
        """
        import re
        help_output = server.handle_run_pipeline("--help")
        # Extract parameter names from "- `param_name` (type...)"
        documented_params = set(re.findall(r"-\s*`(\w+)`", help_output))
        
        tools_dict = {t["name"]: t for t in server.TOOLS}
        self.assertIn("run_pipeline", tools_dict)
        self.assertIn("process_prompt", tools_dict)

        for tool_name in ("run_pipeline", "process_prompt"):
            schema_props = set(tools_dict[tool_name]["inputSchema"]["properties"].keys())
            missing_params = documented_params - schema_props
            self.assertEqual(
                missing_params,
                set(),
                f"Tool '{tool_name}' schema is missing parameters documented in --help: {missing_params}"
            )

    def test_mcp_tools_schema_handler_parity(self):
        """
        Verify that every parameter in python handler function signatures
        is declared in the MCP server TOOLS schema.
        """
        import inspect

        handler_map = {
            "write_file": server.handle_write_file,
            "read_file": server.handle_read_file,
            "ollama_list_models": server.handle_list_models,
            "ollama_chat": server.handle_chat,
            "ollama_task_agent": server.handle_task_agent,
            "ollama_pull_model": server.handle_pull_model,
            "ollama_unload_model": server.handle_unload_model,
            "ollama_execute_task": server.handle_execute_task,
            "ansible_syntax_check": server.handle_ansible_syntax_check,
            "shellcheck_inspect": server.handle_shellcheck_inspect,
            "service_status": server.handle_service_status,
            "journal_logs": server.handle_journal_logs,
            "run_pipeline": server.handle_run_pipeline,
            "process_prompt": server.handle_run_pipeline,
        }

        # Parameters that are strictly internal or injected by tools/call logic
        ignored_params = {
            "ollama_chat": {"tools"},  # internal function tools injected by subagent/task runner
        }

        tools_dict = {t["name"]: t for t in server.TOOLS}

        for tool_name, handler_func in handler_map.items():
            self.assertIn(tool_name, tools_dict, f"Missing tool declaration in server.TOOLS: {tool_name}")
            sig = inspect.signature(handler_func)
            handler_params = set(sig.parameters.keys()) - ignored_params.get(tool_name, set())
            schema_props = set(tools_dict[tool_name]["inputSchema"]["properties"].keys())

            missing_in_schema = handler_params - schema_props
            self.assertEqual(
                missing_in_schema,
                set(),
                f"Tool '{tool_name}' schema does not expose handler parameters: {missing_in_schema}"
            )

    def test_mcp_dispatch_preserves_all_schema_properties(self):
        """
        Verify that tools/call dispatch passes all schema-declared arguments to handler functions.
        """
        # Test ollama_chat accepts top_p and messages
        with patch("server.handle_chat", return_value="mock_chat_response") as mock_chat:
            req = {
                "jsonrpc": "2.0",
                "id": 201,
                "method": "tools/call",
                "params": {
                    "name": "ollama_chat",
                    "arguments": {
                        "model": "winter-coder:latest",
                        "prompt": "Hello",
                        "messages": [{"role": "user", "content": "Hello"}],
                        "system_prompt": "You are an assistant",
                        "temperature": 0.5,
                        "top_p": 0.9,
                        "num_ctx": 8192
                    }
                }
            }
            res = server.process_jsonrpc(req)
            self.assertIsNotNone(res)
            self.assertNotIn("isError", res["result"])
            mock_chat.assert_called_once_with(
                model="winter-coder:latest",
                prompt="Hello",
                messages=[{"role": "user", "content": "Hello"}],
                system_prompt="You are an assistant",
                temperature=0.5,
                top_p=0.9,
                num_ctx=8192
            )

        # Test ollama_task_agent accepts enable_tools
        with patch("server.handle_task_agent", return_value="mock_task_response") as mock_task:
            req = {
                "jsonrpc": "2.0",
                "id": 202,
                "method": "tools/call",
                "params": {
                    "name": "ollama_task_agent",
                    "arguments": {
                        "task": "Test task",
                        "model": "qwen3:8b",
                        "context": "ctx",
                        "task_type": "coding",
                        "enable_tools": False,
                        "num_ctx": 4096
                    }
                }
            }
            res = server.process_jsonrpc(req)
            self.assertIsNotNone(res)
            self.assertNotIn("isError", res["result"])
            mock_task.assert_called_once_with(
                task="Test task",
                model="qwen3:8b",
                context="ctx",
                task_type="coding",
                enable_tools=False,
                num_ctx=4096
            )

    def test_notification_suppression(self):
        """JSON-RPC 2.0: notifications without id must return None to prevent Go jsonrpc client disconnect."""
        req = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }
        res = server.process_jsonrpc(req)
        self.assertIsNone(res)

        # Unrecognized notification method must also return None, not error with id: null
        req_unknown = {
            "jsonrpc": "2.0",
            "method": "$/cancelRequest",
            "params": {"id": 123}
        }
        res_unknown = server.process_jsonrpc(req_unknown)
        self.assertIsNone(res_unknown)

    def test_discovery_endpoints(self):
        """MCP discovery endpoints must return empty collections without error."""
        for endpoint, key in [("resources/list", "resources"), ("prompts/list", "prompts")]:
            req = {"jsonrpc": "2.0", "id": 500, "method": endpoint, "params": {}}
            res = server.process_jsonrpc(req)
            self.assertIsNotNone(res)
            self.assertEqual(res["result"][key], [])

    def test_tool_error_includes_traceback(self):
        """Tool failures must return detailed stack traces in content[0].text."""
        with patch.object(server, "handle_write_file", side_effect=ValueError("Simulated disk error")):
            req = {
                "jsonrpc": "2.0",
                "id": 501,
                "method": "tools/call",
                "params": {
                    "name": "write_file",
                    "arguments": {"path": "invalid.txt", "content": "test"}
                }
            }
            res = server.process_jsonrpc(req)
            self.assertIsNotNone(res)
            self.assertTrue(res["result"].get("isError"))
            text = res["result"]["content"][0]["text"]
            self.assertIn("Simulated disk error", text)
            self.assertIn("=== Traceback ===", text)

    def test_async_run_pipeline(self):
        """Verify run_pipeline with async_run=True returns immediately with started status."""
        with patch("pipeline.run_pipeline") as mock_run:
            req = {
                "jsonrpc": "2.0",
                "id": 600,
                "method": "tools/call",
                "params": {
                    "name": "run_pipeline",
                    "arguments": {
                        "prompt": "Test async prompt",
                        "async_run": True
                    }
                }
            }
            res = server.process_jsonrpc(req)
            self.assertIsNotNone(res)
            self.assertNotIn("isError", res["result"])
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(data["status"], "started")
            self.assertTrue(data.get("async"))
            self.assertIn("run_id", data)

    def test_pipeline_status_tool(self):
        """Verify pipeline_status tool queries run status."""
        req = {
            "jsonrpc": "2.0",
            "id": 601,
            "method": "tools/call",
            "params": {
                "name": "pipeline_status",
                "arguments": {}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        self.assertNotIn("isError", res["result"])
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertIn("status", data)

    def test_inspect_pipeline_run_tool(self):
        """Verify inspect_pipeline_run tool queries deep diagnostics."""
        req = {
            "jsonrpc": "2.0",
            "id": 602,
            "method": "tools/call",
            "params": {
                "name": "inspect_pipeline_run",
                "arguments": {}
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        self.assertNotIn("isError", res["result"])
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertIn("status", data)
        self.assertIn("failure_chronology", data)
        self.assertIn("escalations", data)

    def test_inspect_pipeline_run_historical_run(self):
        """Verify inspect_pipeline_run retrieves failure chronology and escalations for run-20260930-031018-495040."""
        req = {
            "jsonrpc": "2.0",
            "id": 603,
            "method": "tools/call",
            "params": {
                "name": "inspect_pipeline_run",
                "arguments": {
                    "run_id": "run-20260930-031018-495040"
                }
            }
        }
        res = server.process_jsonrpc(req)
        self.assertIsNotNone(res)
        self.assertNotIn("isError", res["result"])
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["run_id"], "run-20260930-031018-495040")
        self.assertEqual(data["status"], "aborted")
        self.assertIn("failure_chronology", data)
        # Should have captured the linter rejections and escalation to codestral
        self.assertTrue(len(data["failure_chronology"]) > 0)
        self.assertTrue(len(data["escalations"]) > 0)
        self.assertEqual(data["escalations"][0]["escalated_model"], "winter-coder:24gb-codestral")


if __name__ == "__main__":
    unittest.main()

