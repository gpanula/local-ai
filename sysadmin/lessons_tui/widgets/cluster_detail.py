"""Detail view showing compaction cluster breakdown, merged rule preview, and member comparison."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from mcp_core.lesson_linter import lint_lesson


class ClusterDetailView(VerticalScroll):
    """Rich detail viewer for the currently selected compaction cluster."""

    DEFAULT_CSS = """
    ClusterDetailView {
        width: 100%;
        height: 1fr;
        padding: 1 2;
        background: $surface-darken-1;
        border: solid $accent;
    }

    #cluster-header {
        margin-bottom: 1;
        height: auto;
    }

    #cluster-meta {
        margin-bottom: 1;
        height: auto;
    }

    .section-title {
        color: $accent;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }

    #merged-rule-box {
        margin: 0 0 1 0;
        height: auto;
    }

    #merged-linter-box {
        margin: 0 0 1 0;
        height: auto;
    }

    #members-box {
        margin: 0 0 1 0;
        height: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cluster: Optional[Dict[str, Any]] = None

    def compose(self) -> ComposeResult:
        yield Static("Select a cluster from the list to preview consolidation.", id="cluster-header")
        yield Static("", id="cluster-meta")
        yield Label("✨ Proposed Merged Rule (to be kept & updated):", classes="section-title")
        yield Static("", id="merged-rule-box")
        yield Label("🛡️ Merged Rule Quality & Safety Check:", classes="section-title")
        yield Static("", id="merged-linter-box")
        yield Label("👥 Member Lessons in this Cluster (candidates to consolidate):", classes="section-title")
        yield Static("", id="members-box")

    def display_cluster(self, cluster: Optional[Dict[str, Any]]) -> None:
        """Update the view with details of the selected cluster."""
        self.cluster = cluster

        header_widget = self.query_one("#cluster-header", Static)
        meta_widget = self.query_one("#cluster-meta", Static)
        rule_widget = self.query_one("#merged-rule-box", Static)
        linter_widget = self.query_one("#merged-linter-box", Static)
        members_widget = self.query_one("#members-box", Static)

        if not cluster:
            header_widget.update("No compaction cluster selected.")
            meta_widget.update("")
            rule_widget.update("")
            linter_widget.update("")
            members_widget.update("")
            return

        idx = cluster.get("cluster_idx", 1)
        cat = cluster.get("category", "General")
        status = cluster.get("status", "pending")
        members = cluster.get("member_objs", [])
        keywords = cluster.get("keywords", [])
        merged_rule = cluster.get("merged_rule", "")
        primary_id = cluster.get("primary_id", members[0]["id"] if members else "unknown")

        # 1. Header
        header_text = Text()
        header_text.append(f"📦 Compaction Cluster #{idx}: ", style="bold white")
        header_text.append(f"{len(members)} Duplicate Candidates ", style="bold magenta")
        header_text.append(f"in Category: '{cat}'", style="cyan")
        header_widget.update(Panel(header_text, style="blue"))

        # 2. Meta Chips
        status_styles = {
            "pending": ("⏳ PENDING REVIEW - Press [c] to Compact, [m] to Modify, [s] to Skip, [d] to Discard", "yellow bold"),
            "compacted": ("✅ COMPACTED & MERGED INTO PRIMARY LESSON", "green bold"),
            "skipped": ("⏭️ SKIPPED (All items kept as-is)", "dim cyan"),
            "discarded": ("🗑️ DISCARDED (All items pruned from queue)", "red bold"),
        }
        status_msg, status_style = status_styles.get(status, (status.upper(), "white"))

        meta_text = Text()
        meta_text.append(f"Status: {status_msg}\n", style=status_style)
        meta_text.append(f"🏷️ Union Keywords ({len(keywords)}): ", style="bold white")
        meta_text.append(", ".join(keywords) if keywords else "none", style="dim cyan")
        meta_text.append(f"\n⭐ Primary Target: ", style="bold white")
        meta_text.append(f"{primary_id} (will be updated with merged rule)", style="green")
        meta_widget.update(meta_text)

        # 3. Merged Rule
        rule_panel = Panel(
            Text(merged_rule, style="bold white"),
            title=f"Merged Rule for {primary_id}",
            border_style="green" if status == "compacted" else "cyan",
        )
        rule_widget.update(rule_panel)

        # 4. Linter Check
        violations = lint_lesson({"id": primary_id, "rule": merged_rule})
        if not violations:
            lint_text = Text("✅ Compliant with all workspace contracts & safety standards.", style="green bold")
        else:
            lint_text = Text(f"🚨 {len(violations)} Safety/Quality Warning(s):\n", style="red bold")
            for v in violations:
                lint_text.append(f"  • [{v.suite}/{v.rule_name}]: {v.message}\n", style="yellow")
        linter_widget.update(Panel(lint_text, border_style="red" if violations else "green"))

        # 5. Member Lessons Comparison
        members_text = Text()
        for i, m in enumerate(members, start=1):
            mid = m.get("id") or m.get("lesson_id") or f"item-{i}"
            mrule = m.get("proposed_rule") or m.get("rule") or ""
            mkws = m.get("keywords") or []
            if isinstance(mkws, str):
                try:
                    import json
                    mkws = json.loads(mkws)
                except Exception:
                    mkws = [mkws]
            critique = m.get("reviewer_critique") or ""

            is_primary = (mid == primary_id)
            if is_primary:
                members_text.append(f"\n┌─ ⭐ [Primary Target] {mid} (Kept & Updated)\n", style="bold green")
            else:
                members_text.append(f"\n┌─ 🗑️ [Duplicate Target] {mid} (Will be Pruned)\n", style="bold red")

            members_text.append(f"│  Rule: {mrule}\n", style="white")
            members_text.append(f"│  Keywords: {', '.join(mkws) if mkws else 'none'}\n", style="dim")
            if critique:
                crit_preview = critique[:120] + "..." if len(critique) > 120 else critique
                members_text.append(f"│  Critique: {crit_preview}\n", style="dim italic")
            members_text.append("└────────────────────────────────────────────────────────────\n", style="dim")

        members_widget.update(members_text)
