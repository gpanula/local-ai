"""Command: ``lint-lessons`` invariant safety & compliance scanner.

Scans lessons in ``ollama_update/lessons.md`` and SQLite ``memory.db``
against tool contracts, safety invariants, test integrity standards,
and workspace rules.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

from mcp_cli.base import BaseCommand, command
from mcp_core.lesson_linter import LessonViolation, format_violation_report, lint_all_lessons, lint_lesson
from mcp_core.lessons_writer import parse_lessons_from_markdown, write_all_lessons_to_markdown
from mcp_core.memory import MemoryStore
from mcp_core.wiki import generate_dashboard, generate_index
from mcp_core.workspace import WORKSPACE_ROOT

DEFAULT_LESSONS_MD = os.path.join(WORKSPACE_ROOT, "ollama_update", "lessons.md")
DEFAULT_WIKI_DIR = os.path.join(WORKSPACE_ROOT, "ollama_update", "wiki")


def _refresh_wiki(lessons: List[dict], wiki_dir: str, action_message: str = "") -> None:
    """Regenerate dashboard.md and index.md in the wiki directory."""
    os.makedirs(wiki_dir, exist_ok=True)
    dashboard_path = os.path.join(wiki_dir, "dashboard.md")
    index_path = os.path.join(wiki_dir, "index.md")
    log_path = os.path.join(wiki_dir, "log.md")

    generate_dashboard(lessons, dashboard_path)
    generate_index(lessons, index_path)

    if action_message:
        from datetime import datetime, timezone
        from mcp_core.wiki import generate_log

        generate_log(
            [
                {
                    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "message": action_message,
                }
            ],
            log_path,
        )


@command
class LintLessonsCommand(BaseCommand):
    """Scan lessons for safety violations, tool contract inversions, and rule contradictions."""

    name = "lint-lessons"
    help = "Scan lessons against safety invariants, tool contracts, and testing standards"

    def register_args(self, parser):
        parser.add_argument(
            "--lessons-md",
            default=DEFAULT_LESSONS_MD,
            help="Path to the Git-canonical lessons.md store (default: ollama_update/lessons.md)",
        )
        parser.add_argument(
            "--wiki-dir",
            default=DEFAULT_WIKI_DIR,
            help="Output directory for wiki files (default: ollama_update/wiki)",
        )
        parser.add_argument(
            "--fix",
            "-f",
            action="store_true",
            help="Interactive remediation mode to delete or rewrite violating lessons",
        )
        parser.add_argument(
            "--check-pending",
            action="store_true",
            default=True,
            help="Also lint staged lessons in the pending review queue (default: True)",
        )
        parser.add_argument(
            "--no-pending",
            dest="check_pending",
            action="store_false",
            help="Skip linting the pending review queue",
        )
        parser.add_argument(
            "--severity",
            choices=["all", "critical"],
            default="all",
            help="Filter displayed violations by severity (default: all)",
        )

    def run(self, args):
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🔍 [Lesson Invariant Linter] Scanning Memory & Lessons Store")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        with MemoryStore() as store:
            db_lessons = store.list_lessons()
            md_lessons = parse_lessons_from_markdown(args.lessons_md)
            # Merge active lessons: lessons.md is Git-canonical, supplemented by SQLite DB
            active_map = {l["id"]: l for l in db_lessons}
            for l in md_lessons:
                active_map[l["id"]] = l
            active_lessons = list(active_map.values())

            pending_lessons = store.list_pending_lessons() if args.check_pending else []

            # Map pending lessons for uniform linting
            mapped_pending = []
            for p in pending_lessons:
                m = dict(p)
                m["rule"] = p.get("proposed_rule", "")
                mapped_pending.append(m)

            active_violations = lint_all_lessons(active_lessons)
            pending_violations = lint_all_lessons(mapped_pending)

            if args.severity == "critical":
                active_violations = {
                    lid: [v for v in viols if v.severity == "CRITICAL"]
                    for lid, viols in active_violations.items()
                }
                active_violations = {lid: viols for lid, viols in active_violations.items() if viols}

                pending_violations = {
                    lid: [v for v in viols if v.severity == "CRITICAL"]
                    for lid, viols in pending_violations.items()
                }
                pending_violations = {lid: viols for lid, viols in pending_violations.items() if viols}

            has_active = bool(active_violations)
            has_pending = bool(pending_violations)

            if not has_active and not has_pending:
                print("\n✅ All active and pending lessons comply with safety & tool invariants.")
                return

            if has_active:
                print(f"\n📂 Active Lessons ({len(active_lessons)} inspected):")
                print(format_violation_report(active_violations))

            if has_pending:
                print(f"\n⏳ Pending Queue Lessons ({len(pending_lessons)} inspected):")
                print(format_violation_report(pending_violations))

            if args.fix:
                self._interactive_remediation(store, active_violations, pending_violations, active_map, args)
            else:
                critical_count = sum(
                    1 for viols in list(active_violations.values()) + list(pending_violations.values())
                    for v in viols if v.severity == "CRITICAL"
                )
                print("\n💡 Run with '--fix' or alias 'localai-lint-lessons-fix' to interactively remediate.")
                if critical_count > 0:
                    sys.exit(1)

    def _interactive_remediation(
        self,
        store: MemoryStore,
        active_violations: Dict[str, List[LessonViolation]],
        pending_violations: Dict[str, List[LessonViolation]],
        active_lessons_map: Dict[str, dict],
        args,
    ) -> None:
        """Prompt developer to delete, modify, or skip violating lessons."""
        print("\n🛠️  [Interactive Remediation Mode]")

        # 1. Remediate active lessons
        if active_violations:
            for lid, viols in list(active_violations.items()):
                lesson = store.get_lesson(lid) or active_lessons_map.get(lid)
                if not lesson:
                    continue

                print("\n" + "=" * 60)
                print(f"Active Lesson: {lid}")
                print(f"Category:      {lesson.get('category', 'unknown')}")
                print(f"Current Rule:  {lesson.get('rule', '')}")
                print("Violations:")
                for v in viols:
                    print(f"  ❌ [{v.suite} / {v.rule_name}]: {v.message}")
                    print(f"     Matched: \"{v.matched_text}\"")
                print("=" * 60)

                while True:
                    choice = input("Action: [d] Delete lesson  [m] Modify rule  [s] Skip  →  ").strip().lower()
                    if choice in ("d", "m", "s"):
                        break
                    print("Invalid choice. Please enter d, m, or s.")

                if choice == "d":
                    store.delete_lesson(lid)
                    remaining = [l for l in parse_lessons_from_markdown(args.lessons_md) if l["id"] != lid]
                    write_all_lessons_to_markdown(remaining, args.lessons_md)
                    _refresh_wiki(remaining, args.wiki_dir, f"Linter remediation: deleted active lesson {lid}")
                    print(f"  🗑️  Deleted active lesson {lid} from database, lessons.md, and wiki.")
                elif choice == "m":
                    new_rule = input(f"Enter new rule text: ").strip()
                    if new_rule:
                        if store.get_lesson(lid):
                            store.update_lesson(
                                lid,
                                {
                                    "rule": new_rule,
                                    "keywords": lesson.get("keywords", []),
                                    "category": lesson.get("category", "unknown"),
                                },
                            )
                        current_md = parse_lessons_from_markdown(args.lessons_md)
                        for l in current_md:
                            if l["id"] == lid:
                                l["rule"] = new_rule
                        write_all_lessons_to_markdown(current_md, args.lessons_md)
                        _refresh_wiki(current_md, args.wiki_dir, f"Linter remediation: updated active lesson {lid}")
                        print(f"  ✏️  Updated active lesson {lid}.")
                    else:
                        print("  ⚠️  Empty rule text — skipped modification.")
                else:
                    print(f"  ⏩ Skipped {lid}.")

        # 2. Remediate pending lessons
        if pending_violations:
            for lid, viols in list(pending_violations.items()):
                pending = store.get_pending_lesson(lid)
                if not pending:
                    continue

                print("\n" + "=" * 60)
                print(f"Pending Lesson: {lid}")
                print(f"Current Rule:   {pending.get('proposed_rule', '')}")
                print("Violations:")
                for v in viols:
                    print(f"  ❌ [{v.suite} / {v.rule_name}]: {v.message}")
                    print(f"     Matched: \"{v.matched_text}\"")
                print("=" * 60)

                while True:
                    choice = input("Action: [d] Discard pending  [m] Modify rule  [s] Skip  →  ").strip().lower()
                    if choice in ("d", "m", "s"):
                        break
                    print("Invalid choice. Please enter d, m, or s.")

                if choice == "d":
                    store.delete_pending_lesson(lid)
                    print(f"  🗑️  Discarded pending lesson {lid} from queue.")
                elif choice == "m":
                    new_rule = input(f"Enter new rule text: ").strip()
                    if new_rule:
                        store.update_pending_lesson(
                            lid,
                            proposed_rule=new_rule,
                            keywords=pending.get("keywords", []),
                            category=pending.get("category", "unknown"),
                        )
                        print(f"  ✏️  Updated pending lesson {lid}.")
                    else:
                        print("  ⚠️  Empty rule text — skipped modification.")
                else:
                    print(f"  ⏩ Skipped pending {lid}.")
