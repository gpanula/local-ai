"""List widget for navigating candidate lesson compaction clusters."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import ListItem, ListView, Static


class ClusterItemWidget(ListItem):
    """Custom list item widget representing a single candidate compaction cluster."""

    DEFAULT_CSS = """
    ClusterItemWidget {
        padding: 0 1;
        height: auto;
    }
    ClusterItemWidget:hover {
        background: $surface-lighten-1;
    }
    ClusterItemWidget.-selected {
        background: $primary-darken-2;
    }
    """

    def __init__(self, cluster: Dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        self.cluster = cluster

    def _build_text(self) -> Text:
        idx = self.cluster.get("cluster_idx", 1)
        cat = self.cluster.get("category", "General")
        status = self.cluster.get("status", "pending")
        members = self.cluster.get("member_objs", [])
        merged_rule = self.cluster.get("merged_rule", "")

        # Status badge & icon
        if status == "compacted":
            status_badge = "[MERGED]"
            badge_style = "green bold"
            status_icon = "✅"
        elif status == "discarded":
            status_badge = "[DISCARD]"
            badge_style = "red bold"
            status_icon = "🗑️"
        elif status == "skipped":
            status_badge = "[SKIPPED]"
            badge_style = "dim cyan"
            status_icon = "⏭️"
        else:
            status_badge = "[PENDING]"
            badge_style = "yellow bold"
            status_icon = "⏳"

        text = Text()
        text.append(f"{status_icon} ")
        text.append(f"{status_badge} ", style=badge_style)
        text.append(f"Cluster #{idx} ", style="bold white")
        text.append(f"({len(members)} lessons) ", style="bold magenta")
        text.append(f"[{cat}]", style="dim cyan")
        if merged_rule:
            preview = merged_rule[:45] + "..." if len(merged_rule) > 45 else merged_rule
            text.append(f"\n   ↳ {preview}", style="dim")

        return text

    def compose(self) -> ComposeResult:
        yield Static(self._build_text(), id="cluster-label")

    def update_content(self) -> None:
        """Refresh this item's visual representation without recreating the widget."""
        try:
            static = self.query_one("#cluster-label", Static)
            static.update(self._build_text())
        except Exception:
            pass


class ClusterListView(ListView):
    """List view managing compaction clusters navigation."""

    DEFAULT_CSS = """
    ClusterListView {
        width: 100%;
        height: 1fr;
        border: solid $secondary;
        background: $surface;
    }
    """

    class ClusterSelected(Message):
        """Emitted when a cluster is highlighted or selected in the list."""

        def __init__(self, cluster: Dict[str, Any]):
            super().__init__()
            self.cluster = cluster

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.clusters: List[Dict[str, Any]] = []

    def set_clusters(self, clusters: List[Dict[str, Any]], keep_index: Optional[int] = None) -> None:
        """Populate the list with given clusters."""
        self.clusters = clusters
        self.clear()

        for c in self.clusters:
            self.append(ClusterItemWidget(c))

        if clusters:
            target_idx = keep_index if (keep_index is not None and 0 <= keep_index < len(clusters)) else 0
            self.index = target_idx

    def refresh_items(self) -> None:
        """Update existing item widgets in place without clearing the list or resetting selection."""
        for child in self.children:
            if isinstance(child, ClusterItemWidget):
                child.update_content()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, ClusterItemWidget):
            self.post_message(self.ClusterSelected(event.item.cluster))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and isinstance(event.item, ClusterItemWidget):
            self.post_message(self.ClusterSelected(event.item.cluster))
