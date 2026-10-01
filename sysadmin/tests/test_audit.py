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


# --- normalize_category (Phase 6.10) ---

from mcp_core.audit import normalize_category


def test_normalize_category_alias_takes_priority():
    """Known LLM alias strings map directly to canonical names via fast-path."""
    assert normalize_category([], "Scripting Best Practices") == "Defensive Bash Scripting"
    assert normalize_category([], "Script Robustness") == "Defensive Bash Scripting"
    assert normalize_category([], "Script Output Compliance") == "Defensive Bash Scripting"
    assert normalize_category([], "Script Creation Method") == "Defensive Bash Scripting"
    assert normalize_category([], "Script Development") == "Binary Isolation"
    assert normalize_category([], "Script Modification") == "Binary Isolation"
    assert normalize_category([], "Code Quality & Pre-Flight Linters") == "ShellCheck"


def test_normalize_category_keyword_scoring():
    """Keyword signals steer category even when the raw category is blank."""
    assert normalize_category(["bash", "cleanup trap", "exit codes"], "") == "Defensive Bash Scripting"
    assert normalize_category(["shellcheck", "sc2034", "quoting"], "") == "ShellCheck"
    assert normalize_category(["binary", "venv", "isolation"], "") == "Binary Isolation"
    assert normalize_category(["ansible", "yaml", "become"], "") == "Ansible"
    assert normalize_category(["python", "syntax", "pytest"], "") == "Python Quality"


def test_normalize_category_fragmented_labels_unify():
    """The real-world fragmentation we observed: all variants map to same canonical."""
    fragments = [
        "Scripting Practices",
        "Script Robustness",
        "Script Output Compliance",
        "Script Creation Method",
        "Scripting Best Practices",
    ]
    for cat in fragments:
        assert normalize_category([], cat) == "Defensive Bash Scripting", f"Failed for: {cat!r}"


def test_normalize_category_fallback_preserves_unknown_raw():
    """Categories with no matching signals and no alias fall back to raw value."""
    result = normalize_category([], "Some Exotic Domain XYZ")
    assert result == "Some Exotic Domain XYZ"


def test_normalize_category_fallback_empty_to_unknown():
    """Empty category + no matching keywords → 'unknown'."""
    assert normalize_category([], "") == "unknown"
    assert normalize_category([], "   ") == "unknown"


def test_normalize_category_staged_lesson_uses_taxonomy(tmp_path):
    """Staging a lesson with a fragmented category normalizes it before insertion."""
    from mcp_core.memory import MemoryStore

    db_path = str(tmp_path / "memory.db")
    with MemoryStore(db_path) as store:
        store.stage_pending_lesson({
            "proposed_rule": "Always include EXIT trap.",
            "category": "Scripting Practices",
            "keywords": ["bash", "cleanup trap"],
        })
        pending = store.list_pending_lessons()

    assert len(pending) == 1
    assert pending[0]["category"] == "Defensive Bash Scripting"


def test_is_canonical_category():
    from mcp_core.audit import is_canonical_category

    assert is_canonical_category("Defensive Bash Scripting") is True
    assert is_canonical_category("ShellCheck") is True
    assert is_canonical_category("Binary Isolation") is True
    assert is_canonical_category("Novel Unmapped Domain") is False
    assert is_canonical_category("unknown") is False
    assert is_canonical_category("") is False


def test_add_taxonomy_domain_dynamic(tmp_path):
    import json
    from mcp_core.audit import add_taxonomy_domain, is_canonical_category, normalize_category

    tax_path = str(tmp_path / "taxonomy.json")
    # Add Docker domain with keywords and alias
    add_taxonomy_domain(
        "Docker & Containers",
        keywords=["docker", "container", "dockerfile"],
        aliases=["dockerization"],
        taxonomy_path=tax_path,
    )

    assert is_canonical_category("Docker & Containers", taxonomy_path=tax_path) is True
    assert normalize_category([], "dockerization", taxonomy_path=tax_path) == "Docker & Containers"
    assert normalize_category(["dockerfile", "container"], "", taxonomy_path=tax_path) == "Docker & Containers"

    # Verify persisted JSON structure
    with open(tax_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "Docker & Containers" in data["taxonomies"]
    assert data["aliases"]["dockerization"] == "Docker & Containers"


