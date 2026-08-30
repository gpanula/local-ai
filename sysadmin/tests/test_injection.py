"""Unit tests for mcp_core.injection.format_lessons_for_prompt (Phase 4.01)."""

from mcp_core.injection import format_lessons_for_prompt


def _lesson(**overrides):
    base = {
        "id": "lesson-20260829-01",
        "category": "sysadmin_bash",
        "keywords": ["heredoc", "EOF"],
        "rule": "Use unindented heredoc delimiters on column 0.",
    }
    base.update(overrides)
    return base


def test_empty_list_returns_empty_string():
    assert format_lessons_for_prompt([]) == ""


def test_single_lesson_renders_section():
    out = format_lessons_for_prompt([_lesson()])
    assert "### Relevant Lessons from Past Runs" in out
    assert "Use unindented heredoc delimiters on column 0." in out
    assert "sysadmin_bash" in out
    assert "heredoc, EOF" in out


def test_three_lessons_produce_three_numbered_blocks():
    lessons = [
        _lesson(id="l1", rule="Rule one"),
        _lesson(id="l2", rule="Rule two"),
        _lesson(id="l3", rule="Rule three"),
    ]
    out = format_lessons_for_prompt(lessons)
    assert "1. **Rule**: Rule one" in out
    assert "2. **Rule**: Rule two" in out
    assert "3. **Rule**: Rule three" in out


def test_output_contains_no_raw_json():
    lessons = [_lesson(rule='{"category": "x"}')]
    out = format_lessons_for_prompt(lessons)
    # The rule text is rendered as-is, but no JSON object braces should appear
    # from the lesson structure itself.
    assert "{\"category\"" not in out.replace('{"category": "x"}', "")


def test_accepts_pending_lesson_shape():
    # Pending lessons use proposed_rule instead of rule.
    out = format_lessons_for_prompt(
        [{"id": "p1", "category": "unknown", "keywords": [], "proposed_rule": "A pending rule"}]
    )
    assert "A pending rule" in out
