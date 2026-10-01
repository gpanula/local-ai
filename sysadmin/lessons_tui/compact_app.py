"""Main Textual Application for Pending Lessons Compaction & Deduplication."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Label, Static

from mcp_core.audit import cluster_lessons
from mcp_core.memory import DEFAULT_DB_PATH, MemoryStore
from lessons_tui.widgets.cluster_detail import ClusterDetailView
from lessons_tui.widgets.cluster_list import ClusterItemWidget, ClusterListView
from lessons_tui.widgets.edit_modal import EditLessonModal


class CompactQueueApp(App):
    """Interactive TUI for reviewing, compacting, and deduplicating pending lessons."""

    CSS = """
    Screen {
        background: $background;
    }

    #top-bar {
        height: 3;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $primary;
    }

    #app-title {
        text-style: bold;
        color: $accent;
        width: 44;
    }

    #stats-badge {
        width: 1fr;
        color: $text-muted;
        text-align: right;
        text-style: bold;
    }

    #main-container {
        height: 1fr;
        width: 100%;
    }

    #left-panel {
        width: 42;
        height: 100%;
        border-right: solid $primary-darken-2;
    }

    #panel-header {
        height: 1;
        padding: 0 1;
        background: $surface-lighten-1;
        color: $accent;
        text-style: bold;
    }

    #right-panel {
        width: 1fr;
        height: 100%;
    }

    #notification-bar {
        height: 1;
        background: $surface;
        color: $accent;
        padding: 0 1;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "compact", "Compact/Merge"),
        Binding("m", "modify", "Modify & Merge"),
        Binding("s", "skip", "Skip"),
        Binding("d", "discard", "Discard Cluster"),
        Binding("a", "auto_compact", "Auto-Compact All"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        min_cluster_size: int = 2,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.min_cluster_size = min_cluster_size
        self.clusters: List[Dict[str, Any]] = []
        self.selected_cluster: Optional[Dict[str, Any]] = None
        self._reload_clusters_from_db()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top-bar"):
            yield Label("🧹 Local AI - Pending Lessons Compactor", id="app-title")
            yield Label("Loading candidate clusters...", id="stats-badge")

        with Horizontal(id="main-container"):
            with Vertical(id="left-panel"):
                yield Label("📦 Candidate Duplicate Clusters", id="panel-header")
                yield ClusterListView(id="cluster-list")
            with Vertical(id="right-panel"):
                yield ClusterDetailView(id="cluster-detail")

        yield Static("Welcome to Lessons Compaction. Select a cluster and press [c] to merge.", id="notification-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._update_ui()

    def _notify_user(self, message: str) -> None:
        try:
            bar = self.query_one("#notification-bar", Static)
            bar.update(message)
        except Exception:
            pass

    def _update_stats(self) -> None:
        try:
            total = len(self.clusters)
            compacted = sum(1 for c in self.clusters if c.get("status") == "compacted")
            discarded = sum(1 for c in self.clusters if c.get("status") == "discarded")
            skipped = sum(1 for c in self.clusters if c.get("status") == "skipped")
            pending = sum(1 for c in self.clusters if c.get("status") == "pending")

            badge = self.query_one("#stats-badge", Label)
            badge.update(
                f"Clusters: {total} | ⏳ Pending: {pending} | ✅ Merged: {compacted} | ⏭️ Skipped: {skipped} | 🗑️ Discarded: {discarded}"
            )
        except Exception:
            pass

    def _reload_clusters_from_db(self) -> None:
        """Fetch pending lessons from database and build clusters."""
        try:
            with MemoryStore(self.db_path) as store:
                pending_list = store.list_pending_lessons()
        except Exception:
            pending_list = []

        if not pending_list:
            self.clusters = []
            self.selected_cluster = None
            return

        mapped_pending = []
        for p in pending_list:
            mapped = dict(p)
            mapped["rule"] = p.get("proposed_rule", "")
            mapped_pending.append(mapped)

        raw_clusters = cluster_lessons(mapped_pending, min_cluster_size=self.min_cluster_size)

        clusters: List[Dict[str, Any]] = []
        for idx, cluster in enumerate(raw_clusters, start=1):
            member_ids = cluster.get("lesson_ids", [])
            member_objs = [p for p in pending_list if p.get("id") in member_ids]
            if len(member_objs) < 2:
                continue

            best_rule = max((p.get("proposed_rule", "") for p in member_objs), key=len)
            merged_critiques = "\n".join(
                f"[{p['id']}] {p.get('reviewer_critique', '')}"
                for p in member_objs if p.get("reviewer_critique")
            )
            merged_keywords = list(dict.fromkeys(cluster.get("keywords", [])))
            category = cluster.get("category", member_objs[0].get("category", "General"))
            primary_id = member_objs[0]["id"]

            clusters.append({
                "cluster_idx": idx,
                "category": category,
                "keywords": merged_keywords,
                "member_ids": member_ids,
                "member_objs": member_objs,
                "best_rule": best_rule,
                "merged_rule": best_rule,
                "merged_critiques": merged_critiques,
                "primary_id": primary_id,
                "status": "pending",
            })

        self.clusters = clusters
        if self.clusters:
            self.selected_cluster = self.clusters[0]
        else:
            self.selected_cluster = None

    def _update_ui(self) -> None:
        """Safely refresh the views with current clusters."""
        try:
            list_view = self.query_one("#cluster-list", ClusterListView)
            detail_view = self.query_one("#cluster-detail", ClusterDetailView)
        except Exception:
            return

        list_view.set_clusters(self.clusters)
        if self.clusters:
            if not self.selected_cluster or self.selected_cluster not in self.clusters:
                self.selected_cluster = self.clusters[0]
            list_view.index = self.clusters.index(self.selected_cluster)
            detail_view.display_cluster(self.selected_cluster)
            self._notify_user(f"📋 Loaded {len(self.clusters)} candidate compaction cluster(s).")
        else:
            self.selected_cluster = None
            detail_view.display_cluster(None)
            self._notify_user("📋 Pending Queue: No duplicate clusters found.")

        self._update_stats()

    def action_refresh(self) -> None:
        """Reload pending lessons from database and refresh UI."""
        self._reload_clusters_from_db()
        self._update_ui()

    @on(ClusterListView.ClusterSelected)
    def on_cluster_selected(self, event: ClusterListView.ClusterSelected) -> None:
        self.selected_cluster = event.cluster
        try:
            detail_view = self.query_one("#cluster-detail", ClusterDetailView)
            detail_view.display_cluster(self.selected_cluster)
        except Exception:
            pass

    def _advance_to_next_pending(self) -> None:
        list_view = self.query_one("#cluster-list", ClusterListView)
        current_idx = list_view.index if list_view.index is not None else 0

        # Try to find next pending cluster starting from current+1
        next_idx = None
        for i in range(current_idx + 1, len(self.clusters)):
            if self.clusters[i].get("status") == "pending":
                next_idx = i
                break

        if next_idx is None:
            # Wrap around from beginning
            for i in range(0, current_idx):
                if self.clusters[i].get("status") == "pending":
                    next_idx = i
                    break

        if next_idx is not None and next_idx < len(list_view.children):
            list_view.index = next_idx
            self.selected_cluster = self.clusters[next_idx]
            detail_view = self.query_one("#cluster-detail", ClusterDetailView)
            detail_view.display_cluster(self.selected_cluster)
        else:
            # All done or stayed on current
            detail_view = self.query_one("#cluster-detail", ClusterDetailView)
            detail_view.display_cluster(self.selected_cluster)

    def _execute_compact(self, cluster: Dict[str, Any]) -> bool:
        primary_id = cluster["primary_id"]
        member_objs = cluster["member_objs"]
        best_rule = cluster["merged_rule"]
        category = cluster["category"]
        keywords = cluster["keywords"]
        critiques = cluster["merged_critiques"]

        try:
            with MemoryStore(self.db_path) as store:
                store.conn.execute(
                    "UPDATE pending_lessons SET proposed_rule = ?, category = ?, keywords = ?, reviewer_critique = ? WHERE id = ?",
                    (best_rule, category, json.dumps(keywords), critiques, primary_id),
                )
                store.conn.commit()

                # Remove duplicates
                pruned_count = 0
                for m in member_objs:
                    mid = m.get("id")
                    if mid and mid != primary_id:
                        store.delete_pending_lesson(mid)
                        pruned_count += 1

            cluster["status"] = "compacted"
            return True
        except Exception as e:
            self._notify_user(f"❌ Error compacting cluster: {e}")
            return False

    def action_compact(self) -> None:
        """Compact/merge the currently selected cluster."""
        if not self.selected_cluster:
            self._notify_user("⚠️ No cluster selected to compact.")
            return

        if self.selected_cluster.get("status") != "pending":
            self._notify_user(f"⚠️ Cluster #{self.selected_cluster.get('cluster_idx')} already marked as {self.selected_cluster.get('status')}.")
            return

        cluster = self.selected_cluster
        idx = cluster.get("cluster_idx")
        count = len(cluster.get("member_objs", []))
        primary_id = cluster.get("primary_id")

        if self._execute_compact(cluster):
            self._notify_user(f"✅ Compacted Cluster #{idx} ({count} items) into primary lesson '{primary_id}'.")
            list_view = self.query_one("#cluster-list", ClusterListView)
            list_view.set_clusters(self.clusters)
            self._update_stats()
            self._advance_to_next_pending()

    def action_modify(self) -> None:
        """Open modal to modify category, merged rule, or keywords before merging."""
        if not self.selected_cluster:
            self._notify_user("⚠️ No cluster selected to modify.")
            return

        if self.selected_cluster.get("status") != "pending":
            self._notify_user(f"⚠️ Cluster #{self.selected_cluster.get('cluster_idx')} already marked as {self.selected_cluster.get('status')}.")
            return

        cluster = self.selected_cluster
        idx = cluster.get("cluster_idx")
        primary_id = cluster.get("primary_id")

        lesson_dict = {
            "id": primary_id,
            "category": cluster.get("category", ""),
            "proposed_rule": cluster.get("merged_rule", ""),
            "keywords": cluster.get("keywords", []),
        }

        modal = EditLessonModal(
            lesson_dict,
            title=f"✏️ Modify Merged Rule for Cluster #{idx} (Target: {primary_id})",
            save_label="Save & Compact [Ctrl+S]",
        )

        def _on_modal_dismiss(result: Optional[Dict[str, Any]]) -> None:
            if not result:
                self._notify_user("Cancelled modification.")
                return

            cluster["merged_rule"] = result.get("rule", cluster["merged_rule"])
            cluster["category"] = result.get("category", cluster["category"])
            cluster["keywords"] = result.get("keywords", cluster["keywords"])

            # Execute compact with modified values
            if self._execute_compact(cluster):
                self._notify_user(f"✅ Modified & compacted Cluster #{idx} into '{primary_id}'.")
                list_view = self.query_one("#cluster-list", ClusterListView)
                list_view.set_clusters(self.clusters)
                self._update_stats()
                self._advance_to_next_pending()

        self.push_screen(modal, _on_modal_dismiss)

    def action_discard(self) -> None:
        """Discard all pending lessons in the selected cluster."""
        if not self.selected_cluster:
            self._notify_user("⚠️ No cluster selected to discard.")
            return

        if self.selected_cluster.get("status") != "pending":
            self._notify_user(f"⚠️ Cluster #{self.selected_cluster.get('cluster_idx')} already marked as {self.selected_cluster.get('status')}.")
            return

        cluster = self.selected_cluster
        idx = cluster.get("cluster_idx")
        member_objs = cluster.get("member_objs", [])

        try:
            with MemoryStore(self.db_path) as store:
                for m in member_objs:
                    mid = m.get("id")
                    if mid:
                        store.delete_pending_lesson(mid)

            cluster["status"] = "discarded"
            self._notify_user(f"🗑️ Discarded {len(member_objs)} pending lesson(s) from Cluster #{idx}.")
            list_view = self.query_one("#cluster-list", ClusterListView)
            list_view.set_clusters(self.clusters)
            self._update_stats()
            self._advance_to_next_pending()
        except Exception as e:
            self._notify_user(f"❌ Error discarding cluster: {e}")

    def action_skip(self) -> None:
        """Skip the currently selected cluster without modifying database."""
        if not self.selected_cluster:
            self._notify_user("⚠️ No cluster selected.")
            return

        cluster = self.selected_cluster
        idx = cluster.get("cluster_idx")
        if cluster.get("status") == "pending":
            cluster["status"] = "skipped"
            self._notify_user(f"⏭️ Skipped Cluster #{idx}.")
            list_view = self.query_one("#cluster-list", ClusterListView)
            list_view.set_clusters(self.clusters)
            self._update_stats()

        self._advance_to_next_pending()

    def action_auto_compact(self) -> None:
        """Automatically compact all pending candidate clusters."""
        pending_clusters = [c for c in self.clusters if c.get("status") == "pending"]
        if not pending_clusters:
            self._notify_user("ℹ️ No pending candidate clusters left to auto-compact.")
            return

        compacted_count = 0
        for cluster in pending_clusters:
            if self._execute_compact(cluster):
                compacted_count += 1

        self._notify_user(f"🎉 Auto-compacted {compacted_count} candidate cluster(s) successfully!")
        list_view = self.query_one("#cluster-list", ClusterListView)
        list_view.set_clusters(self.clusters)
        self._update_stats()

        detail_view = self.query_one("#cluster-detail", ClusterDetailView)
        detail_view.display_cluster(self.selected_cluster)


def launch_compact_queue_tui(
    db_path: str = DEFAULT_DB_PATH,
    min_cluster_size: int = 2,
) -> None:
    """Launch the CompactQueueApp."""
    app = CompactQueueApp(db_path=db_path, min_cluster_size=min_cluster_size)
    app.run()


if __name__ == "__main__":
    launch_compact_queue_tui()
