"""Memory review commands: ``review-lessons`` interactive human gate.

Phase 3: lets the developer batch-review all staged pending lessons
interactively (Keep / Modify / Discard / Skip). Kept and modified lessons are
promoted to the active ``lessons`` table and appended to the Git-canonical
``ollama_update/lessons.md`` store.
"""

from __future__ import annotations

import os

from mcp_core.lessons_writer import append_lesson_to_markdown
from mcp_core.memory import MemoryStore
from mcp_core.workspace import WORKSPACE_ROOT
from mcp_cli.base import BaseCommand, command

# Default Git-canonical lesson store (relative to workspace root).
DEFAULT_LESSONS_MD = os.path.join(WORKSPACE_ROOT, "ollama_update", "lessons.md")


def _format_keywords(keywords) -> str:
    """Render a keywords list for display."""
    if isinstance(keywords, str):
        return keywords
    if isinstance(keywords, (list, tuple)):
        return ", ".join(str(k) for k in keywords)
    return str(keywords or "")


def _print_review_card(index: int, total: int, pending: dict) -> None:
    """Print a formatted review card for a single pending lesson."""
    print("\n" + "=" * 60)
    print(f"Pending lesson {index}/{total}")
    print("=" * 60)
    print(f"  ID:            {pending.get('id', '')}")
    print(f"  Task file:     {pending.get('task_file', '')}")
    print(f"  Lesson type:   {pending.get('lesson_type', '')}")
    print(f"  Outcome:       {pending.get('outcome', '')}")
    print(f"  Category:      {pending.get('category', '')}")
    print(f"  Keywords:      {_format_keywords(pending.get('keywords', []))}")
    print("-" * 60)
    print("  Reviewer critique:")
    print(f"    {pending.get('reviewer_critique', '')}")
    print("-" * 60)
    print("  Proposed rule:")
    print(f"    {pending.get('proposed_rule', '')}")
    print("=" * 60)


def _prompt_action() -> str:
    """Prompt the developer for an action, returning a normalized choice."""
    while True:
        choice = input("  [k] Keep  [m] Modify  [d] Discard  [s] Skip  →  ").strip().lower()
        if choice in ("k", "m", "d", "s"):
            return choice
        print("  Invalid choice. Please enter k, m, d, or s.")


def _prompt_modify(pending: dict) -> dict:
    """Prompt for optional rule-text and keyword edits. Returns an edits dict."""
    edits: dict = {}
    print("\n  Modify lesson (press Enter to keep current value):")
    new_rule = input(f"  Rule [{pending.get('proposed_rule', '')}]: ").strip()
    if new_rule:
        edits["rule"] = new_rule
    new_keywords = input(
        f"  Keywords [{_format_keywords(pending.get('keywords', []))}] (comma-separated): "
    ).strip()
    if new_keywords:
        edits["keywords"] = [k.strip() for k in new_keywords.split(",") if k.strip()]
    return edits


@command
class ReviewLessonsCommand(BaseCommand):
    name = "review-lessons"
    help = "Interactively review staged pending lessons (Keep / Modify / Discard / Skip)"

    def register_args(self, parser):
        parser.add_argument(
            "--lessons-md",
            default=DEFAULT_LESSONS_MD,
            help="Path to the Git-canonical lessons.md store (default: ollama_update/lessons.md)",
        )

    def run(self, args):
        lessons_md_path = args.lessons_md
        with MemoryStore() as store:
            pending = store.list_pending_lessons()

            if not pending:
                print("✅ No pending lessons to review.")
                return

            counts = {"kept": 0, "modified": 0, "discarded": 0, "skipped": 0}
            total = len(pending)

            for index, item in enumerate(pending, start=1):
                _print_review_card(index, total, item)
                action = _prompt_action()

                if action == "k":
                    lesson_id = store.promote_pending_lesson(item["id"])
                    if lesson_id:
                        promoted = store.get_lesson(lesson_id)
                        if promoted:
                            append_lesson_to_markdown(promoted, lessons_md_path)
                        counts["kept"] += 1
                        print(f"  ✅ Kept lesson {lesson_id} and appended to lessons.md")
                    else:
                        print("  ⚠️  Could not promote lesson (already removed?)")

                elif action == "m":
                    edits = _prompt_modify(item)
                    lesson_id = store.promote_pending_lesson(item["id"], edits=edits)
                    if lesson_id:
                        promoted = store.get_lesson(lesson_id)
                        if promoted:
                            append_lesson_to_markdown(promoted, lessons_md_path)
                        counts["modified"] += 1
                        print(f"  ✏️  Modified and kept lesson {lesson_id}")
                    else:
                        print("  ⚠️  Could not promote lesson (already removed?)")

                elif action == "d":
                    store.delete_pending_lesson(item["id"])
                    counts["discarded"] += 1
                    print(f"  🗑️  Discarded pending lesson {item['id']}")

                else:  # skip
                    counts["skipped"] += 1
                    print(f"  ⏭️  Skipped pending lesson {item['id']}")

            print("\n" + "=" * 60)
            print(
                f"Summary — Kept: {counts['kept']} | Modified: {counts['modified']} | "
                f"Discarded: {counts['discarded']} | Skipped: {counts['skipped']}"
            )
            print("=" * 60)
