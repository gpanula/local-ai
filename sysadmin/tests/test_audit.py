"""Unit tests for mcp_core.audit — clustering and low-utility flagging (Phase 6.01/6.03)."""

from mcp_core.audit import cluster_lessons, flag_low_utility


def _lesson(lesson_id, keywords, category="sysadmin_bash", **overrides):
    base = {
        "id": lesson_id,
        "keywords": keywords,
        "category": category,
        "rule": f"Rule for {lesson_id}",
        "retrieval_count": 0,
        "prevented_rework_count": 0,
        "ineffective_count": 0,
    }
    base.update(overrides)
    return base


# --- clustering ---

def test_heredoc_lessons_cluster_together():
    lessons = [
        _lesson("l1", ["heredoc", "EOF", "delimiter"]),
        _lesson("l2", ["heredoc", "EOF"]),
        _lesson("l3", ["heredoc", "delimiter"]),
        _lesson("l4", ["EOF", "delimiter"]),
        _lesson("l5", ["heredoc", "EOF", "delimiter"]),
    ]
    clusters = cluster_lessons(lessons, min_cluster_size=3)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["count"] == 5
    assert set(cluster["lesson_ids"]) == {"l1", "l2", "l3", "l4", "l5"}
    # Keywords are normalized to lowercase by the clustering engine.
    assert "heredoc" in cluster["keywords"]
    assert "eof" in cluster["keywords"]


def test_unrelated_lessons_do_not_cluster_at_size_3():
    lessons = [
        _lesson("l1", ["heredoc", "EOF"]),
        _lesson("l2", ["ansible", "become"]),
    ]
    clusters = cluster_lessons(lessons, min_cluster_size=3)
    assert clusters == []


def test_cluster_sorted_by_size_descending():
    lessons = [
        _lesson("a1", ["heredoc", "EOF"], category="bash"),
        _lesson("a2", ["heredoc", "EOF"], category="bash"),
        _lesson("a3", ["heredoc", "EOF"], category="bash"),
        _lesson("a4", ["heredoc", "EOF"], category="bash"),
        _lesson("b1", ["ansible", "become"], category="ansible"),
        _lesson("b2", ["ansible", "become"], category="ansible"),
        _lesson("b3", ["ansible", "become"], category="ansible"),
    ]
    clusters = cluster_lessons(lessons, min_cluster_size=3)
    sizes = [c["count"] for c in clusters]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes[0] == 4


def test_cluster_is_pure_function_no_io():
    """cluster_lessons takes a list and returns a list — no DB/file side effects."""
    lessons = [_lesson("l1", ["heredoc", "EOF"]), _lesson("l2", ["heredoc", "EOF"])]
    result = cluster_lessons(lessons, min_cluster_size=2)
    assert isinstance(result, list)
    assert result[0]["count"] == 2


def test_empty_lessons_returns_empty():
    assert cluster_lessons([], min_cluster_size=3) == []


# --- low-utility flagging ---

def test_flag_lesson_with_8_retrievals_0_preventions():
    lessons = [_lesson("l1", ["heredoc"], retrieval_count=8, prevented_rework_count=0)]
    flagged = flag_low_utility(lessons, min_retrievals=5, max_prevention_ratio=0.3)
    assert len(flagged) == 1
    assert flagged[0]["id"] == "l1"
    assert flagged[0]["prevention_ratio"] == 0.0
    # utility_score = (0+1)/(8+2) = 0.1
    assert abs(flagged[0]["utility_score"] - 0.1) < 1e-9


def test_not_flag_lesson_with_50_percent_prevention():
    lessons = [_lesson("l1", ["heredoc"], retrieval_count=8, prevented_rework_count=4)]
    flagged = flag_low_utility(lessons, min_retrievals=5, max_prevention_ratio=0.3)
    assert flagged == []


def test_not_flag_below_min_retrievals():
    lessons = [_lesson("l1", ["heredoc"], retrieval_count=3, prevented_rework_count=0)]
    flagged = flag_low_utility(lessons, min_retrievals=5, max_prevention_ratio=0.3)
    assert flagged == []


def test_flag_lesson_at_exact_threshold_boundary():
    # 5 retrievals, 1 prevention -> ratio 0.2 < 0.3 -> flagged.
    lessons = [_lesson("l1", ["heredoc"], retrieval_count=5, prevented_rework_count=1)]
    flagged = flag_low_utility(lessons, min_retrievals=5, max_prevention_ratio=0.3)
    assert len(flagged) == 1
    assert abs(flagged[0]["prevention_ratio"] - 0.2) < 1e-9
