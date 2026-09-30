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


def test_normalize_lesson_rule_handles_punctuation_and_whitespace():
    from mcp_core.injection import normalize_lesson_rule

    r1 = "Proactive risk mitigation for sysadmin: Zero environmental side effects."
    r2 = "  proactive risk mitigation for sysadmin zero environmental side effects   "
    assert normalize_lesson_rule(r1) == normalize_lesson_rule(r2)
    assert normalize_lesson_rule("") == ""
    assert normalize_lesson_rule(None) == ""


def test_deduplicate_lessons_by_id():
    from mcp_core.injection import deduplicate_lessons

    lessons = [
        _lesson(id="l1", rule="Rule A"),
        _lesson(id="l1", rule="Rule B"),
        _lesson(id="l2", rule="Rule C"),
    ]
    deduped = deduplicate_lessons(lessons)
    assert len(deduped) == 2
    assert [d["id"] for d in deduped] == ["l1", "l2"]
    assert deduped[0]["rule"] == "Rule A"


def test_deduplicate_lessons_by_normalized_rule():
    from mcp_core.injection import deduplicate_lessons

    lessons = [
        _lesson(id="lesson-20260918-43", rule="Proactive risk mitigation for sysadmin: Zero side effects."),
        _lesson(id="lesson-20260918-45", rule="Proactive risk mitigation for sysadmin: Zero side effects."),
        _lesson(id="lesson-20260918-56", rule="proactive risk mitigation for sysadmin zero side effects"),
        _lesson(id="lesson-20260918-99", rule="Completely different rule."),
    ]
    deduped = deduplicate_lessons(lessons)
    assert len(deduped) == 2
    assert deduped[0]["id"] == "lesson-20260918-43"
    assert deduped[1]["id"] == "lesson-20260918-99"


def test_format_lessons_for_prompt_deduplicates_duplicate_rules():
    lessons = [
        _lesson(id="lesson-1", rule="Never write unquoted variables."),
        _lesson(id="lesson-2", rule="Never write unquoted variables!"),
        _lesson(id="lesson-3", rule="Ensure error traps are present."),
    ]
    out = format_lessons_for_prompt(lessons)
    # Should only have two numbered blocks (1 and 2), not 3
    assert "1. **Rule**: Never write unquoted variables." in out
    assert "2. **Rule**: Ensure error traps are present." in out
    assert "3. **Rule**" not in out
