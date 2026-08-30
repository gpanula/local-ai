"""Unit tests for mcp_core.rules_writer.append_system_rule (Phase 6.02)."""

import os

from mcp_core.rules_writer import append_system_rule

SKELETON = (
    "# Universal System Rules\n\n"
    "> **Purpose**: Curated defensive engineering invariants.\n\n"
    "<!-- Rules are appended below this line by the audit-lessons promotion flow. -->\n"
)


def _write_skeleton(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(SKELETON)


def test_append_first_rule_to_skeleton(tmp_path):
    path = os.path.join(str(tmp_path), "SYSTEM_RULES.md")
    _write_skeleton(path)
    append_system_rule("Always use set -euo pipefail.", ["lesson-20260829-01"], path)

    content = open(path, encoding="utf-8").read()
    assert "### Rule #1" in content
    assert "**Promoted**:" in content
    assert "**Source Lessons**: lesson-20260829-01" in content
    assert "Always use set -euo pipefail." in content


def test_append_second_rule_produces_rule_2(tmp_path):
    path = os.path.join(str(tmp_path), "SYSTEM_RULES.md")
    _write_skeleton(path)
    append_system_rule("Rule one.", ["l1"], path)
    append_system_rule("Rule two.", ["l2", "l3"], path)

    content = open(path, encoding="utf-8").read()
    assert "### Rule #1" in content
    assert "### Rule #2" in content
    assert "**Source Lessons**: l2, l3" in content


def test_provenance_includes_date_and_source_ids(tmp_path):
    path = os.path.join(str(tmp_path), "SYSTEM_RULES.md")
    _write_skeleton(path)
    append_system_rule("Rule text.", ["a", "b"], path)

    content = open(path, encoding="utf-8").read()
    assert "**Promoted**:" in content
    assert "**Source Lessons**: a, b" in content


def test_append_creates_file_if_missing(tmp_path):
    path = os.path.join(str(tmp_path), "nested", "SYSTEM_RULES.md")
    append_system_rule("Rule text.", ["l1"], path)
    assert os.path.exists(path)
    content = open(path, encoding="utf-8").read()
    assert "### Rule #1" in content


def test_rule_number_increments_from_existing_headers(tmp_path):
    path = os.path.join(str(tmp_path), "SYSTEM_RULES.md")
    _write_skeleton(path)
    # Pre-seed a rule #3 to verify numbering continues from max.
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n### Rule #3: Existing\n**Promoted**: 2026-08-29 | **Source Lessons**: x\n\nold\n")
    append_system_rule("New rule.", ["l1"], path)
    content = open(path, encoding="utf-8").read()
    assert "### Rule #4" in content
