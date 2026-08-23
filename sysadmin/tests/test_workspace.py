"""Unit tests for mcp_core.workspace path validation (server.py canonical semantics)."""

import os

import pytest

from mcp_core.workspace import WORKSPACE_ROOT, is_valid_mcp_socket, validate_workspace_path


def test_workspace_root_is_absolute_and_contains_core():
    assert os.path.isabs(WORKSPACE_ROOT)
    core_dir = os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_core"))
    assert core_dir.startswith(WORKSPACE_ROOT + os.sep)


def test_validate_accepts_absolute_inside_workspace():
    target = os.path.join(WORKSPACE_ROOT, "README.md")
    assert validate_workspace_path(target) == os.path.realpath(target)


def test_validate_resolves_relative_against_workspace_root():
    # Canonicalized server semantics: relative paths resolve against WORKSPACE_ROOT,
    # NOT the current working directory.
    resolved = validate_workspace_path("sysadmin/mcp_client.py")
    assert resolved == os.path.join(WORKSPACE_ROOT, "sysadmin", "mcp_client.py")


def test_validate_rejects_path_outside_workspace(tmp_path):
    outside = os.path.join(tmp_path, "secret.txt")
    with pytest.raises(ValueError, match="outside workspace"):
        validate_workspace_path(outside)


def test_validate_rejects_empty_path():
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_workspace_path(bad, purpose="test")


def test_is_valid_mcp_socket_false_for_regular_file(tmp_path):
    f = tmp_path / "not_a_socket"
    f.write_text("x")
    assert is_valid_mcp_socket(str(f)) is False


def test_is_valid_mcp_socket_false_for_missing():
    assert is_valid_mcp_socket("/tmp/definitely_not_a_socket_xyz") is False
