"""Unit tests for the CompactQueueApp Textual TUI."""

from __future__ import annotations

import asyncio
import os
import pytest

from mcp_core.memory import MemoryStore
from lessons_tui.compact_app import CompactQueueApp
from lessons_tui.widgets.cluster_detail import ClusterDetailView
from lessons_tui.widgets.cluster_list import ClusterListView


@pytest.fixture
def temp_db(tmp_path):
    """Provide isolated database path."""
    return str(tmp_path / "memory.db")


def test_compact_queue_tui_empty(temp_db):
    """Verify app mounts cleanly when pending queue is empty."""
    async def _run():
        app = CompactQueueApp(db_path=temp_db)
        async with app.run_test() as pilot:
            assert len(app.clusters) == 0
            assert app.selected_cluster is None

            list_view = app.query_one("#cluster-list", ClusterListView)
            assert len(list_view.clusters) == 0

            detail_view = app.query_one("#cluster-detail", ClusterDetailView)
            assert detail_view.cluster is None

    asyncio.run(_run())


def test_compact_queue_tui_clustering_and_compact(temp_db):
    """Verify candidate duplicate clusters load and compact action works."""
    with MemoryStore(temp_db) as store:
        store.stage_pending_lesson({
            "id": "pending-dup-01",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting", "sc2086"],
            "reviewer_critique": "Critique 1",
        })
        store.stage_pending_lesson({
            "id": "pending-dup-02",
            "proposed_rule": "Short quote rule.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting", "variables"],
            "reviewer_critique": "Critique 2",
        })

    async def _run():
        app = CompactQueueApp(db_path=temp_db, min_cluster_size=2)
        async with app.run_test() as pilot:
            assert len(app.clusters) == 1
            cluster = app.clusters[0]
            assert cluster["status"] == "pending"
            assert len(cluster["member_objs"]) == 2
            assert cluster["primary_id"] == "pending-dup-01"
            assert "Always quote variables" in cluster["best_rule"]

            list_view = app.query_one("#cluster-list", ClusterListView)
            assert len(list_view.clusters) == 1

            detail_view = app.query_one("#cluster-detail", ClusterDetailView)
            assert detail_view.cluster is not None
            assert detail_view.cluster["primary_id"] == "pending-dup-01"

            # Execute compact action
            app.action_compact()
            assert cluster["status"] == "compacted"

    asyncio.run(_run())

    # Check database state after compact
    with MemoryStore(temp_db) as store:
        remaining = store.list_pending_lessons()
        assert len(remaining) == 1
        primary = remaining[0]
        assert primary["id"] == "pending-dup-01"
        assert "Always quote variables" in primary["proposed_rule"]
        assert "Critique 1" in primary["reviewer_critique"]
        assert "Critique 2" in primary["reviewer_critique"]


def test_compact_queue_tui_discard(temp_db):
    """Verify discarding a cluster deletes all member lessons."""
    with MemoryStore(temp_db) as store:
        store.stage_pending_lesson({
            "id": "pending-discard-01",
            "proposed_rule": "Rule A to discard",
            "category": "Testing",
            "keywords": ["test", "discard"],
        })
        store.stage_pending_lesson({
            "id": "pending-discard-02",
            "proposed_rule": "Rule B to discard",
            "category": "Testing",
            "keywords": ["test", "discard"],
        })

    async def _run():
        app = CompactQueueApp(db_path=temp_db, min_cluster_size=2)
        async with app.run_test() as pilot:
            assert len(app.clusters) == 1
            app.action_discard()
            assert app.clusters[0]["status"] == "discarded"

    asyncio.run(_run())

    with MemoryStore(temp_db) as store:
        remaining = store.list_pending_lessons()
        assert len(remaining) == 0


def test_compact_queue_tui_skip(temp_db):
    """Verify skipping leaves lessons intact in database."""
    with MemoryStore(temp_db) as store:
        store.stage_pending_lesson({
            "id": "pending-skip-01",
            "proposed_rule": "Rule A to skip",
            "category": "Testing",
            "keywords": ["test", "skip"],
        })
        store.stage_pending_lesson({
            "id": "pending-skip-02",
            "proposed_rule": "Rule B to skip",
            "category": "Testing",
            "keywords": ["test", "skip"],
        })

    async def _run():
        app = CompactQueueApp(db_path=temp_db, min_cluster_size=2)
        async with app.run_test() as pilot:
            assert len(app.clusters) == 1
            app.action_skip()
            assert app.clusters[0]["status"] == "skipped"

    asyncio.run(_run())

    with MemoryStore(temp_db) as store:
        remaining = store.list_pending_lessons()
        assert len(remaining) == 2


def test_compact_queue_tui_auto_compact(temp_db):
    """Verify auto-compacting merges all pending clusters."""
    with MemoryStore(temp_db) as store:
        # Cluster 1
        store.stage_pending_lesson({
            "id": "p-c1-01",
            "proposed_rule": "Long rule for cluster 1",
            "category": "Cluster1",
            "keywords": ["c1", "test"],
        })
        store.stage_pending_lesson({
            "id": "p-c1-02",
            "proposed_rule": "Short c1",
            "category": "Cluster1",
            "keywords": ["c1", "test"],
        })
        # Cluster 2
        store.stage_pending_lesson({
            "id": "p-c2-01",
            "proposed_rule": "Long rule for cluster 2",
            "category": "Cluster2",
            "keywords": ["c2", "test"],
        })
        store.stage_pending_lesson({
            "id": "p-c2-02",
            "proposed_rule": "Short c2",
            "category": "Cluster2",
            "keywords": ["c2", "test"],
        })

    async def _run():
        app = CompactQueueApp(db_path=temp_db, min_cluster_size=2)
        async with app.run_test() as pilot:
            assert len(app.clusters) == 2
            app.action_auto_compact()
            assert all(c["status"] == "compacted" for c in app.clusters)

    asyncio.run(_run())

    with MemoryStore(temp_db) as store:
        remaining = store.list_pending_lessons()
        assert len(remaining) == 2
        ids = {r["id"] for r in remaining}
        assert ids == {"p-c1-01", "p-c2-01"}


def test_compact_queue_tui_modify(temp_db):
    """Verify modifying a cluster updates its merged fields before compacting."""
    with MemoryStore(temp_db) as store:
        store.stage_pending_lesson({
            "id": "p-mod-01",
            "proposed_rule": "Original rule text 1",
            "category": "ModCategory",
            "keywords": ["kw1", "kw2"],
        })
        store.stage_pending_lesson({
            "id": "p-mod-02",
            "proposed_rule": "Original rule text 2",
            "category": "ModCategory",
            "keywords": ["kw1", "kw3"],
        })

    app = CompactQueueApp(db_path=temp_db, min_cluster_size=2)
    assert len(app.clusters) == 1
    cluster = app.clusters[0]

    # Directly test _execute_compact with custom modifications
    cluster["merged_rule"] = "Custom user edited rule"
    cluster["category"] = "UpdatedCategory"
    cluster["keywords"] = ["kw1", "kw2", "kw3", "edited"]

    success = app._execute_compact(cluster)
    assert success is True
    assert cluster["status"] == "compacted"

    with MemoryStore(temp_db) as store:
        remaining = store.list_pending_lessons()
        assert len(remaining) == 1
        primary = remaining[0]
        assert primary["id"] == "p-mod-01"
        assert primary["proposed_rule"] == "Custom user edited rule"
        assert primary["category"] == "UpdatedCategory"
        assert "edited" in primary["keywords"]

