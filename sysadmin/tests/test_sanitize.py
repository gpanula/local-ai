"""Unit tests for mcp_core.sanitize.sanitize_script_code."""

from mcp_core.sanitize import sanitize_script_code


def test_dedents_common_indentation():
    code = "    echo hi\n    echo bye\n"
    assert sanitize_script_code(code) == "echo hi\necho bye"


def test_normalizes_heredoc_delimiter():
    code = "cat <<EOF\ntext\n   EOF\n"
    assert sanitize_script_code(code) == "cat <<EOF\ntext\nEOF"


def test_strips_surrounding_whitespace():
    code = "\n\necho hi\n\n"
    assert sanitize_script_code(code) == "echo hi"


def test_leaves_plain_code_unchanged():
    code = "#!/usr/bin/env bash\nset -euo pipefail\necho ok"
    assert sanitize_script_code(code) == code
