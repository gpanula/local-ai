"""Unit tests for mcp_core.wiki — index, dashboard, and log generators (Phase 7.03/7.04)."""

import os

from mcp_core.wiki import generate_dashboard, generate_index, generate_log


def _lesson(lesson_id, category, keywords, rule, **overrides):
    base = {
        "id": lesson_id,
        "category": category,
        "keywords": keywords,
        "rule": rule,
        "source_task": f"sysadmin/prompts/{lesson_id}.md",
        "created": "2026-08-30",
        "retrieval_count": 0,
        "prevented_rework_count": 0,
        "ineffective_count": 0,
    }
    base.update(overrides)
    return base


def test_index_groups_by_category(tmp_path):
    path = os.path.join(str(tmp_path), "index.md")
    lessons = [
        _lesson("l1", "bash", ["heredoc"], "Use unindented heredocs."),
        _lesson("l2", "bash", ["trap"], "Use ERR traps."),
        _lesson("l3", "ansible", ["become"], "Use become."),
        _lesson("l4", "ansible", ["sudo"], "Use sudo."),
        _lesson("l5", "docker", ["volume"], "Mount volumes."),
    ]
    generate_index(lessons, path)
    content = open(path, encoding="utf-8").read()
    assert "## bash" in content
    assert "## ansible" in content
    assert "## docker" in content
    assert "| [[l1]] |" in content
    assert "| [[l3]] |" in content


def test_index_empty_lessons(tmp_path):
    path = os.path.join(str(tmp_path), "index.md")
    generate_index([], path)
    content = open(path, encoding="utf-8").read()
    assert "No lessons recorded." in content


def test_index_is_valid_markdown(tmp_path):
    path = os.path.join(str(tmp_path), "index.md")
    generate_index([_lesson("l1", "bash", ["heredoc"], "Rule text.")], path)
    content = open(path, encoding="utf-8").read()
    assert content.startswith("# Lesson Index")
    assert "| ID | Keywords | Rule | Source Task | Created |" in content


def test_dashboard_has_leaderboard_sections(tmp_path):
    path = os.path.join(str(tmp_path), "dashboard.md")
    lessons = [
        _lesson("l1", "bash", ["heredoc"], "r", retrieval_count=10, prevented_rework_count=0),
        _lesson("l2", "bash", ["trap"], "r", retrieval_count=2, prevented_rework_count=1),
        _lesson("l3", "ansible", ["become"], "r", retrieval_count=8, prevented_rework_count=0),
    ]
    generate_dashboard(lessons, path)
    content = open(path, encoding="utf-8").read()
    assert "## Top-Retrieved Lessons" in content
    assert "## Highest-Utility Lessons" in content
    assert "## Promotion Candidates" in content
    assert "## Low-Utility Flags" in content


def test_dashboard_empty_lessons(tmp_path):
    path = os.path.join(str(tmp_path), "dashboard.md")
    generate_dashboard([], path)
    content = open(path, encoding="utf-8").read()
    assert "No lessons recorded." in content


def test_log_is_append_only(tmp_path):
    path = os.path.join(str(tmp_path), "log.md")
    generate_log([{"timestamp": "2026-08-30T00:00:00", "message": "first"}], path)
    generate_log([{"timestamp": "2026-08-30T00:00:01", "message": "second"}], path)
    content = open(path, encoding="utf-8").read()
    assert "first" in content
    assert "second" in content
    # Both entries present (append-only, not overwritten).
    assert content.count("- `") == 2


def test_log_empty_events_noop(tmp_path):
    path = os.path.join(str(tmp_path), "log.md")
    generate_log([], path)
    assert not os.path.exists(path)
