"""Memory review commands: ``review-lessons`` interactive human gate.

Phase 3: lets the developer batch-review all staged pending lessons
interactively (Keep / Modify / Discard / Skip). Kept and modified lessons are
promoted to the active ``lessons`` table and appended to the Git-canonical
``ollama_update/lessons.md`` store.
"""

from __future__ import annotations

import json
import os

from mcp_core.audit import cluster_lessons, flag_low_utility, is_canonical_category, normalize_category
from mcp_core.lessons_writer import append_lesson_to_markdown, write_all_lessons_to_markdown
from mcp_core.memory import MemoryStore
from mcp_core.rules_writer import append_system_rule
from mcp_core.wiki import generate_dashboard, generate_index, generate_log
from mcp_core.workspace import WORKSPACE_ROOT
from mcp_cli.base import BaseCommand, command

# Default Git-canonical lesson store (relative to workspace root).
DEFAULT_LESSONS_MD = os.path.join(WORKSPACE_ROOT, "ollama_update", "lessons.md")

# Default universal system rules store (relative to workspace root).
DEFAULT_SYSTEM_RULES_MD = os.path.join(WORKSPACE_ROOT, "sysadmin", "prompts", "SYSTEM_RULES.md")

# Archive store for lessons promoted into universal rules (relative to workspace root).
DEFAULT_LESSONS_ARCHIVE_MD = os.path.join(WORKSPACE_ROOT, "ollama_update", "lessons_archive.md")

# Wiki output directory (relative to workspace root).
DEFAULT_WIKI_DIR = os.path.join(WORKSPACE_ROOT, "ollama_update", "wiki")


def _format_keywords(keywords) -> str:
    """Render a keywords list or JSON string as comma-separated text."""
    if isinstance(keywords, str):
        try:
            parsed = json.loads(keywords)
            if isinstance(parsed, list):
                keywords = parsed
        except (json.JSONDecodeError, TypeError):
            pass
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
    cat = pending.get("category", "")
    badge = "  [✅ Canonical Taxonomy]" if is_canonical_category(cat) else "  [🆕 Novel Domain - Not in Taxonomy]"
    print(f"  Category:      {cat}{badge}")
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
    """Prompt for optional category, rule-text, and keyword edits. Returns an edits dict."""
    edits: dict = {}
    print("\n  Modify lesson (press Enter to keep current value):")
    new_cat = input(f"  Category [{pending.get('category', '')}]: ").strip()
    if new_cat:
        edits["category"] = normalize_category(pending.get("keywords", []), new_cat)
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
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Automatically accept and promote all staged pending lessons without prompting",
        )
        parser.add_argument(
            "--wiki-dir",
            default=DEFAULT_WIKI_DIR,
            help="Output directory for wiki files (default: ollama_update/wiki)",
        )

    def run(self, args):
        lessons_md_path = args.lessons_md
        with MemoryStore() as store:
            pending = store.list_pending_lessons()

            if not pending:
                print("✅ No pending lessons to review.")
                return

            if getattr(args, "auto", False):
                promoted_count = 0
                for item in pending:
                    lesson_id = store.promote_pending_lesson(item["id"])
                    if lesson_id:
                        promoted = store.get_lesson(lesson_id)
                        if promoted:
                            append_lesson_to_markdown(promoted, lessons_md_path)
                        promoted_count += 1
                        print(f"  ✅ Kept lesson {lesson_id} ({item.get('id')})")
                print("\n" + "=" * 60)
                print(f"Summary — Automatically Kept: {promoted_count} | Total: {len(pending)}")
                print("=" * 60)

                # Auto-recompile wiki
                wiki_dir = getattr(args, "wiki_dir", DEFAULT_WIKI_DIR)
                if wiki_dir and promoted_count > 0:
                    updated_lessons = store.list_lessons()
                    os.makedirs(wiki_dir, exist_ok=True)
                    index_path = os.path.join(wiki_dir, "index.md")
                    dashboard_path = os.path.join(wiki_dir, "dashboard.md")
                    log_path = os.path.join(wiki_dir, "log.md")
                    generate_index(updated_lessons, index_path)
                    generate_dashboard(updated_lessons, dashboard_path)
                    from datetime import datetime, timezone

                    generate_log(
                        [
                            {
                                "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                                "message": f"Wiki re-compiled after auto-promoting {promoted_count} lesson(s).",
                            }
                        ],
                        log_path,
                    )
                    print(f"📚 Wiki re-compiled: index.md ({len(updated_lessons)} active lessons), dashboard.md, log.md")
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

            # Auto-recompile wiki if lessons changed
            wiki_dir = getattr(args, "wiki_dir", DEFAULT_WIKI_DIR)
            if wiki_dir and (counts["kept"] > 0 or counts["modified"] > 0):
                updated_lessons = store.list_lessons()
                os.makedirs(wiki_dir, exist_ok=True)
                index_path = os.path.join(wiki_dir, "index.md")
                dashboard_path = os.path.join(wiki_dir, "dashboard.md")
                log_path = os.path.join(wiki_dir, "log.md")
                generate_index(updated_lessons, index_path)
                generate_dashboard(updated_lessons, dashboard_path)
                from datetime import datetime, timezone

                generate_log(
                    [
                        {
                            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            "message": f"Wiki re-compiled after promoting {counts['kept'] + counts['modified']} lesson(s).",
                        }
                    ],
                    log_path,
                )
                print(f"📚 Wiki re-compiled: index.md ({len(updated_lessons)} active lessons), dashboard.md, log.md")


def _format_keywords_display(keywords) -> str:
    """Render a keywords list for display (list or string)."""
    if isinstance(keywords, str):
        return keywords
    if isinstance(keywords, (list, tuple)):
        return ", ".join(str(k) for k in keywords)
    return str(keywords or "")


def _append_to_archive(lesson: dict, archive_path: str) -> None:
    """Append a lesson to the archive store in canonical YAML-frontmatter form."""
    append_lesson_to_markdown(lesson, archive_path)


@command
class AuditLessonsCommand(BaseCommand):
    name = "audit-lessons"
    help = "Cluster related lessons, promote recurring patterns to SYSTEM_RULES.md, flag low-utility lessons"

    def register_args(self, parser):
        parser.add_argument(
            "--rules-md",
            default=DEFAULT_SYSTEM_RULES_MD,
            help="Path to SYSTEM_RULES.md (default: sysadmin/prompts/SYSTEM_RULES.md)",
        )
        parser.add_argument(
            "--archive-md",
            default=DEFAULT_LESSONS_ARCHIVE_MD,
            help="Path to lessons_archive.md (default: ollama_update/lessons_archive.md)",
        )
        parser.add_argument(
            "--min-cluster-size",
            type=int,
            default=3,
            help="Minimum cluster size to consider for promotion (default: 3)",
        )
        parser.add_argument(
            "--min-retrievals",
            type=int,
            default=5,
            help="Minimum retrieval count to flag a lesson as low-utility (default: 5)",
        )

    def run(self, args):
        with MemoryStore() as store:
            lessons = store.list_lessons()
            if not lessons:
                print("✅ No active lessons to audit.")
                return

            clusters = cluster_lessons(lessons, min_cluster_size=args.min_cluster_size)
            low_utility = flag_low_utility(lessons, min_retrievals=args.min_retrievals)

            counts = {"promoted": 0, "modified": 0, "kept": 0, "discarded": 0,
                      "deleted": 0, "rewritten": 0, "skipped": 0}

            # --- Cluster review / promotion ---
            if clusters:
                print("\n" + "=" * 60)
                print(f"📦 {len(clusters)} promotion candidate cluster(s) found")
                print("=" * 60)
                for idx, cluster in enumerate(clusters, start=1):
                    self._review_cluster(store, cluster, idx, len(clusters), args, counts)
            else:
                print("\n📦 No promotion candidate clusters found.")

            # --- Low-utility review ---
            if low_utility:
                print("\n" + "=" * 60)
                print(f"⚠️  {len(low_utility)} low-utility lesson(s) flagged for cleanup")
                print("=" * 60)
                for idx, lesson in enumerate(low_utility, start=1):
                    self._review_low_utility(store, lesson, idx, len(low_utility), counts)
            else:
                print("\n⚠️  No low-utility lessons flagged.")

            print("\n" + "=" * 60)
            print(
                f"Summary — Promoted: {counts['promoted']} | Modified: {counts['modified']} | "
                f"Kept: {counts['kept']} | Discarded: {counts['discarded']} | "
                f"Deleted: {counts['deleted']} | Rewritten: {counts['rewritten']} | "
                f"Skipped: {counts['skipped']}"
            )
            print("=" * 60)

    def _review_cluster(self, store, cluster, index, total, args, counts) -> None:
        """Prompt for an action on a single promotion candidate cluster."""
        print("\n" + "-" * 60)
        print(f"Cluster {index}/{total} — {cluster['count']} lessons")
        print(f"  Category:   {cluster['category']}")
        print(f"  Keywords:   {_format_keywords_display(cluster['keywords'])}")
        print(f"  Lesson IDs: {', '.join(str(i) for i in cluster['lesson_ids'])}")
        print("-" * 60)

        while True:
            choice = input(
                "  [p] Promote to SYSTEM_RULES.md  [m] Modify rule  "
                "[k] Keep as episodic  [d] Discard cluster  →  "
            ).strip().lower()
            if choice in ("p", "m", "k", "d"):
                break
            print("  Invalid choice. Please enter p, m, k, or d.")

        if choice == "p":
            rule_text = self._cluster_rule_text(cluster)
            self._promote_cluster(store, cluster, rule_text, args, counts)
        elif choice == "m":
            rule_text = input("  New rule text: ").strip()
            if not rule_text:
                print("  ⚠️  Empty rule text — treating as Keep.")
                counts["kept"] += 1
                return
            self._promote_cluster(store, cluster, rule_text, args, counts)
        elif choice == "k":
            counts["kept"] += 1
            print(f"  📌 Kept {cluster['count']} lesson(s) as episodic.")
        else:  # discard
            for lesson_id in cluster["lesson_ids"]:
                store.delete_lesson(lesson_id)
            counts["discarded"] += 1
            print(f"  🗑️  Discarded cluster ({cluster['count']} lesson(s)).")

    @staticmethod
    def _cluster_rule_text(cluster) -> str:
        """Build a default rule text from a cluster's keywords and category."""
        kw = ", ".join(cluster["keywords"]) if cluster["keywords"] else "related topics"
        return (
            f"Recurring pattern across {cluster['count']} lessons in category "
            f"'{cluster['category']}' (keywords: {kw}). Consolidate these into a "
            f"single universal defensive invariant."
        )

    def _promote_cluster(self, store, cluster, rule_text, args, counts) -> None:
        """Promote a cluster: write SYSTEM_RULES.md, archive lessons, delete active."""
        append_system_rule(rule_text, cluster["lesson_ids"], args.rules_md)
        for lesson_id in cluster["lesson_ids"]:
            lesson = store.get_lesson(lesson_id)
            if lesson:
                _append_to_archive(lesson, args.archive_md)
            store.delete_lesson(lesson_id)
        counts["promoted"] += 1
        print(
            f"  🏆 Promoted rule to SYSTEM_RULES.md and archived "
            f"{cluster['count']} lesson(s)."
        )

    def _review_low_utility(self, store, lesson, index, total, counts) -> None:
        """Prompt for an action on a single low-utility lesson."""
        print("\n" + "-" * 60)
        print(f"Low-utility lesson {index}/{total}")
        print(f"  ID:              {lesson.get('id', '')}")
        print(f"  Retrievals:      {lesson.get('retrieval_count', 0)}")
        print(f"  Prevented:       {lesson.get('prevented_rework_count', 0)}")
        print(f"  Prevention ratio:{lesson.get('prevention_ratio', 0.0):.2f}")
        print(f"  Utility score:   {lesson.get('utility_score', 0.0):.2f}")
        print(f"  Rule:            {lesson.get('rule', '')}")
        print("-" * 60)

        while True:
            choice = input("  [d] Delete  [m] Rewrite keywords/rule  [s] Skip  →  ").strip().lower()
            if choice in ("d", "m", "s"):
                break
            print("  Invalid choice. Please enter d, m, or s.")

        if choice == "d":
            store.delete_lesson(lesson["id"])
            counts["deleted"] += 1
            print(f"  🗑️  Deleted low-utility lesson {lesson['id']}.")
        elif choice == "m":
            new_rule = input(f"  Rule [{lesson.get('rule', '')}]: ").strip()
            new_keywords = input(
                f"  Keywords [{_format_keywords_display(lesson.get('keywords', []))}] "
                "(comma-separated): "
            ).strip()
            updates = {}
            if new_rule:
                updates["rule"] = new_rule
            if new_keywords:
                updates["keywords"] = [k.strip() for k in new_keywords.split(",") if k.strip()]
            if updates:
                store.update_lesson(lesson["id"], updates)
                counts["rewritten"] += 1
                print(f"  ✏️  Rewrote lesson {lesson['id']}.")
            else:
                counts["skipped"] += 1
                print(f"  ⏭️  No changes — skipped lesson {lesson['id']}.")
        else:  # skip
            counts["skipped"] += 1
            print(f"  ⏭️  Skipped lesson {lesson['id']}.")


@command
class CompileWikiCommand(BaseCommand):
    name = "compile-wiki"
    help = "Generate the memory-health wiki (index.md, dashboard.md, log.md)"

    def register_args(self, parser):
        parser.add_argument(
            "--wiki-dir",
            default=DEFAULT_WIKI_DIR,
            help="Output directory for wiki files (default: ollama_update/wiki)",
        )

    def run(self, args):
        wiki_dir = args.wiki_dir
        os.makedirs(wiki_dir, exist_ok=True)

        index_path = os.path.join(wiki_dir, "index.md")
        dashboard_path = os.path.join(wiki_dir, "dashboard.md")
        log_path = os.path.join(wiki_dir, "log.md")

        with MemoryStore() as store:
            lessons = store.list_lessons()

        generate_index(lessons, index_path)
        generate_dashboard(lessons, dashboard_path)
        # Log a compile event (append-only).
        from datetime import datetime, timezone

        generate_log(
            [
                {
                    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "message": f"Wiki compiled with {len(lessons)} active lessons.",
                }
            ],
            log_path,
        )

        print(
            f"📚 Wiki compiled: index.md ({len(lessons)} lessons), dashboard.md, log.md"
        )


@command
class CompactLessonsCommand(BaseCommand):
    name = "compact-lessons"
    help = "Consolidate and deduplicate similar lessons across pending queue and active memory"

    def register_args(self, parser):
        parser.add_argument(
            "--queue-only",
            action="store_true",
            help="Compact only the pending review queue",
        )
        parser.add_argument(
            "--active-only",
            action="store_true",
            help="Compact only active approved lessons",
        )
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Automatically merge duplicate clusters without interactive prompts",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview proposed consolidations without writing changes",
        )
        parser.add_argument(
            "--min-cluster-size",
            type=int,
            default=2,
            help="Minimum cluster size to consolidate (default: 2)",
        )
        parser.add_argument(
            "--lessons-md",
            default=DEFAULT_LESSONS_MD,
            help="Path to the Git-canonical lessons.md store",
        )
        parser.add_argument(
            "--wiki-dir",
            default=DEFAULT_WIKI_DIR,
            help="Output directory for wiki files (default: ollama_update/wiki)",
        )

    def run(self, args):
        with MemoryStore() as store:
            do_queue = not args.active_only
            do_active = not args.queue_only

            print("=" * 60)
            print("🧹 Memory Compaction & Lesson Consolidation Engine")
            print("=" * 60)

            # --- 1. Compact Pending Queue ---
            if do_queue:
                self._compact_pending(store, args)

            # --- 2. Compact Active Lessons ---
            if do_active:
                self._compact_active(store, args)

    def _compact_pending(self, store: MemoryStore, args) -> None:
        pending_list = store.list_pending_lessons()
        if not pending_list:
            print("\n📋 Pending Queue: No pending lessons to compact.")
            return

        # Map pending fields for clustering
        mapped_pending = []
        for p in pending_list:
            mapped = dict(p)
            mapped["rule"] = p.get("proposed_rule", "")
            mapped_pending.append(mapped)

        clusters = cluster_lessons(mapped_pending, min_cluster_size=args.min_cluster_size)
        print(f"\n📋 Pending Queue: Found {len(clusters)} compaction candidate cluster(s) from {len(pending_list)} pending lessons.")

        for idx, cluster in enumerate(clusters, start=1):
            member_ids = cluster["lesson_ids"]
            member_objs = [p for p in pending_list if p["id"] in member_ids]
            if len(member_objs) < 2:
                continue

            # Pick best rule (longest / most descriptive)
            best_rule = max((p.get("proposed_rule", "") for p in member_objs), key=len)
            merged_critiques = "\n".join(
                f"[{p['id']}] {p.get('reviewer_critique', '')}"
                for p in member_objs if p.get("reviewer_critique")
            )
            merged_keywords = list(dict.fromkeys(cluster.get("keywords", [])))
            category = cluster.get("category", member_objs[0].get("category", "unknown"))

            print("-" * 60)
            print(f"📦 [Pending Cluster {idx}/{len(clusters)}] {len(member_objs)} items -> {member_ids}")
            print(f"  Category: {category}")
            print(f"  Keywords: {', '.join(merged_keywords)}")
            print(f"  Merged Rule: {best_rule}")
            print("-" * 60)

            if args.dry_run:
                print("  🔍 [Dry Run] Would consolidate cluster into single pending item.")
                continue

            if not args.auto:
                choice = input("  [c] Compact / Merge  [s] Skip  [d] Discard cluster  →  ").strip().lower()
                if choice == "d":
                    for pid in member_ids:
                        store.delete_pending_lesson(pid)
                    print(f"  🗑️ Discarded {len(member_ids)} pending lessons.")
                    continue
                elif choice != "c":
                    print("  ⏭️ Skipped cluster.")
                    continue

            # Keep primary, update with merged fields, delete others
            primary_id = member_ids[0]
            store.conn.execute(
                "UPDATE pending_lessons SET proposed_rule = ?, category = ?, keywords = ?, reviewer_critique = ? WHERE id = ?",
                (best_rule, category, json.dumps(merged_keywords), merged_critiques, primary_id),
            )
            for other_id in member_ids[1:]:
                store.delete_pending_lesson(other_id)
            store.conn.commit()
            print(f"  ✅ Compacted {len(member_ids)} pending lessons into '{primary_id}'.")

    def _compact_active(self, store: MemoryStore, args) -> None:
        active_list = store.list_lessons()
        if not active_list:
            print("\n📚 Active Lessons: No active lessons to compact.")
            return

        clusters = cluster_lessons(active_list, min_cluster_size=args.min_cluster_size)
        print(f"\n📚 Active Lessons: Found {len(clusters)} compaction candidate cluster(s) from {len(active_list)} active lessons.")

        modified = False
        for idx, cluster in enumerate(clusters, start=1):
            member_ids = cluster["lesson_ids"]
            member_objs = [l for l in active_list if l["id"] in member_ids]
            if len(member_objs) < 2:
                continue

            best_rule = max((l.get("rule", "") for l in member_objs), key=len)
            merged_keywords = list(dict.fromkeys(cluster.get("keywords", [])))
            category = cluster.get("category", member_objs[0].get("category", "unknown"))

            # Sum telemetry counters
            total_retrievals = sum(int(l.get("retrieval_count", 0)) for l in member_objs)
            total_prevented = sum(int(l.get("prevented_rework_count", 0)) for l in member_objs)
            total_ineffective = sum(int(l.get("ineffective_count", 0)) for l in member_objs)

            print("-" * 60)
            print(f"📦 [Active Cluster {idx}/{len(clusters)}] {len(member_objs)} items -> {member_ids}")
            print(f"  Category: {category}")
            print(f"  Keywords: {', '.join(merged_keywords)}")
            print(f"  Merged Rule: {best_rule}")
            print(f"  Combined Telemetry: {total_retrievals} retrievals, {total_prevented} prevented rework")
            print("-" * 60)

            if args.dry_run:
                print("  🔍 [Dry Run] Would consolidate cluster into single active lesson.")
                continue

            if not args.auto:
                choice = input("  [c] Compact / Merge  [s] Skip  [d] Discard cluster  →  ").strip().lower()
                if choice == "d":
                    for lid in member_ids:
                        store.delete_lesson(lid)
                    modified = True
                    print(f"  🗑️ Discarded {len(member_ids)} active lessons.")
                    continue
                elif choice != "c":
                    print("  ⏭️ Skipped cluster.")
                    continue

            primary_id = member_ids[0]
            store.update_lesson(primary_id, {
                "rule": best_rule,
                "category": category,
                "keywords": merged_keywords,
                "retrieval_count": total_retrievals,
                "prevented_rework_count": total_prevented,
                "ineffective_count": total_ineffective,
            })
            for other_id in member_ids[1:]:
                store.delete_lesson(other_id)
            modified = True
            print(f"  ✅ Compacted {len(member_ids)} active lessons into '{primary_id}'.")

        if modified and not args.dry_run:
            updated_lessons = store.list_lessons()
            write_all_lessons_to_markdown(updated_lessons, args.lessons_md)
            print(f"\n📝 Re-synced {args.lessons_md} with {len(updated_lessons)} active lessons.")

            # Auto-recompile wiki dashboard, index, and log
            wiki_dir = getattr(args, "wiki_dir", DEFAULT_WIKI_DIR)
            if wiki_dir:
                os.makedirs(wiki_dir, exist_ok=True)
                index_path = os.path.join(wiki_dir, "index.md")
                dashboard_path = os.path.join(wiki_dir, "dashboard.md")
                log_path = os.path.join(wiki_dir, "log.md")
                generate_index(updated_lessons, index_path)
                generate_dashboard(updated_lessons, dashboard_path)
                from datetime import datetime, timezone
                generate_log(
                    [
                        {
                            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            "message": f"Wiki re-compiled after memory compaction ({len(updated_lessons)} active lessons).",
                        }
                    ],
                    log_path,
                )
                print(f"📚 Wiki re-compiled: index.md ({len(updated_lessons)} lessons), dashboard.md, log.md")

