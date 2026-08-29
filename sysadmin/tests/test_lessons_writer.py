"""Unit tests for mcp_core.lessons_writer.append_lesson_to_markdown (Phase 3.01).

Verifies the canonical YAML-frontmatter format, first-lesson handling, and that
appending multiple lessons does not corrupt prior content.
"""

import os

from mcp_core.lessons_writer import append_lesson_to_markdown

SKELETON = (
    "# Lessons Learned — Episodic Memory Store\n\n"
    "<!-- Lessons are appended below this line by the review-lessons promotion flow. -->\n"
)


def _lesson(**overrides):
    """A promoted (active-lesson shape) lesson dict."""
    base = {
        "id": "lesson-20260829-01",
        "category": "sysadmin_bash",
        "keywords": ["trap", "write_file", "direct_execution"],
        "rule": "Never nest script content inside subshell strings.",
        "created": "2026-08-29",
        "source_task": "sysadmin/prompts/hello_world_test.md",
        "lesson_type": "solved_pattern",
    }
    base.update(overrides)
    return base


def _write_skeleton(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(SKELETON)


def test_append_first_lesson_to_skeleton(tmp_path):
    path = os.path.join(str(tmp_path), "lessons.md")
    _write_skeleton(path)
    append_lesson_to_markdown(_lesson(), path)

    content = open(path, encoding="utf-8").read()
    # Skeleton header preserved.
    assert "# Lessons Learned" in content
    # Canonical frontmatter fields present.
    assert "id: lesson-20260829-01" in content
    assert "category: sysadmin_bash" in content
    assert "keywords: [trap, write_file, direct_execution]" in content
    assert "created: 2026-08-29" in content
    assert "source_task: sysadmin/prompts/hello_world_test.md" in content
    assert "**Rule**: Never nest script content inside subshell strings." in content


def test_append_second_lesson_does_not_corrupt_first(tmp_path):
    path = os.path.join(str(tmp_path), "lessons.md")
    _write_skeleton(path)
    append_lesson_to_markdown(_lesson(id="lesson-20260829-01"), path)
    append_lesson_to_markdown(
        _lesson(id="lesson-20260829-02", keywords=["heredoc", "EOF"],
                rule="Heredoc delimiters at column 0."),
        path,
    )

    content = open(path, encoding="utf-8").read()
    # Both lessons present.
    assert "id: lesson-20260829-01" in content
    assert "id: lesson-20260829-02" in content
    assert "**Rule**: Never nest script content inside subshell strings." in content
    assert "**Rule**: Heredoc delimiters at column 0." in content
    # Each block is delimited by its own frontmatter.
    assert content.count("---") == 4  # 2 blocks x 2 delimiters


def test_append_accepts_pending_shape(tmp_path):
    """The writer tolerates pending-lesson field names (proposed_rule/task_file)."""
    path = os.path.join(str(tmp_path), "lessons.md")
    _write_skeleton(path)
    append_lesson_to_markdown(
        {
            "id": "pending-20260829-01",
            "category": "ansible",
            "keywords": ["become", "sudo"],
            "proposed_rule": "Use become: true for privilege escalation.",
            "task_file": "sysadmin/prompts/ansible_venv.md",
            "created": "2026-08-29",
        },
        path,
    )
    content = open(path, encoding="utf-8").read()
    assert "**Rule**: Use become: true for privilege escalation." in content
    assert "source_task: sysadmin/prompts/ansible_venv.md" in content


def test_append_creates_file_if_missing(tmp_path):
    path = os.path.join(str(tmp_path), "nested", "lessons.md")
    append_lesson_to_markdown(_lesson(), path)
    assert os.path.exists(path)
    content = open(path, encoding="utf-8").read()
    assert "id: lesson-20260829-01" in content
