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
        self.assertIn("ollama_list_models", tool_names)
        self.assertIn("ollama_chat", tool_names)
        self.assertIn("ollama_task_agent", tool_names)
        self.assertIn("ollama_pull_model", tool_names)

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


if __name__ == "__main__":
    unittest.main()
