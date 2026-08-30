"""Unit tests for mcp_core.attribution.attribute_lessons (Phase 5.02)."""

from mcp_core.attribution import attribute_lessons


def _lesson(lesson_id, keywords):
    return {"id": lesson_id, "keywords": keywords, "rule": "rule"}


def test_iteration_one_pass_credits_all():
    lessons = [_lesson("l1", ["heredoc"]), _lesson("l2", ["ansible"])]
    result = {"iterations": 1, "approved": True}
    att = attribute_lessons(lessons, result, "")
    assert att == {"l1": "credited", "l2": "credited"}


def test_lesson_with_overlapping_keyword_is_blamed():
    lessons = [_lesson("l1", ["heredoc"])]
    result = {"iterations": 2, "approved": True}
    att = attribute_lessons(lessons, result, "- Fix heredoc delimiter indentation")
    assert att == {"l1": "blamed"}


def test_lesson_without_overlap_is_innocent():
    lessons = [_lesson("l2", ["ansible"])]
    result = {"iterations": 2, "approved": True}
    att = attribute_lessons(lessons, result, "- Fix heredoc delimiter indentation")
    assert att == {"l2": "innocent"}


def test_mixed_attribution():
    lessons = [_lesson("l1", ["heredoc"]), _lesson("l2", ["ansible"])]
    result = {"iterations": 2, "approved": False}
    att = attribute_lessons(lessons, result, "- Fix heredoc delimiter indentation")
    assert att == {"l1": "blamed", "l2": "innocent"}


def test_lessons_without_id_are_skipped():
    lessons = [{"keywords": ["heredoc"]}]
    result = {"iterations": 2, "approved": True}
    assert attribute_lessons(lessons, result, "- heredoc") == {}


def test_keywords_as_json_string():
    import json

    lesson = {"id": "l1", "keywords": json.dumps(["heredoc", "EOF"])}
    result = {"iterations": 2, "approved": True}
    att = attribute_lessons([lesson], result, "- Fix heredoc")
    assert att == {"l1": "blamed"}
