"""Unit tests for the mcp_cli command registry and argparse wiring."""

import argparse
import sys

import pytest

from mcp_cli.base import COMMAND_REGISTRY
from mcp_cli.cli import build_parser

EXPECTED_COMMANDS = {
    "list-models", "pull", "chat", "task", "task-file", "exec",
    "build-and-run", "pipeline-run", "type", "view", "ansible-check",
    "shellcheck", "service-status", "journal-logs", "write-file", "read-file",
    "review-lessons", "audit-lessons",
}


def test_all_commands_registered():
    assert set(COMMAND_REGISTRY) == EXPECTED_COMMANDS


def test_build_parser_has_all_subcommands():
    parser = build_parser()
    sub_actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert sub_actions
    names = set()
    for action in sub_actions:
        names.update(action.choices.keys())
    assert EXPECTED_COMMANDS.issubset(names)


@pytest.mark.parametrize("command", sorted(EXPECTED_COMMANDS))
def test_each_subcommand_parses_help(command):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([command, "--help"])
    assert exc.value.code == 0


def test_chat_default_model():
    parser = build_parser()
    args = parser.parse_args(["chat", "hello"])
    assert args.model == "qwen3:8b"


def test_list_models_runs_with_mocked_transport(fake_call_mcp, capsys):
    parser = build_parser()
    args = parser.parse_args(["list-models"])
    COMMAND_REGISTRY["list-models"].run(args)
    captured = capsys.readouterr()
    assert captured.out.strip() == "mocked"
    assert fake_call_mcp == [("ollama_list_models", {})]


def test_type_command_uses_fake_terminal_session(fake_terminal_session, capsys):
    parser = build_parser()
    args = parser.parse_args(["type", "echo hi"])
    COMMAND_REGISTRY["type"].run(args)
    captured = capsys.readouterr()
    assert "Typed into terminal-mcp: echo hi" in captured.out
    # _FakeTerminalSession records typed text
    last_session = fake_terminal_session()
    assert last_session is not None


def test_write_file_requires_content(monkeypatch):
    class _TTYStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", _TTYStdin())
    parser = build_parser()
    args = parser.parse_args(["write-file", "some/path.txt"])
    with pytest.raises(ValueError, match="No content provided"):
        COMMAND_REGISTRY["write-file"].run(args)
