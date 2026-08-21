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


if __name__ == "__main__":
    unittest.main()
