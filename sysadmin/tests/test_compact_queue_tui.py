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
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting", "sc2086"],
            "reviewer_critique": "Critique 1",
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "pending-dup-02",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting", "variables"],
            "reviewer_critique": "Critique 2",
        }, deduplicate=False)

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
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "Testing",
            "keywords": ["test", "discard"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "pending-discard-02",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "Testing",
            "keywords": ["test", "discard"],
        }, deduplicate=False)

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
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "Testing",
            "keywords": ["test", "skip"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "pending-skip-02",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "Testing",
            "keywords": ["test", "skip"],
        }, deduplicate=False)

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
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "Cluster1",
            "keywords": ["c1", "test"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "p-c1-02",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "Cluster1",
            "keywords": ["c1", "test"],
        }, deduplicate=False)
        # Cluster 2
        store.stage_pending_lesson({
            "id": "p-c2-01",
            "proposed_rule": "Always isolate python virtual environments in sysadmin scripts before running tools.",
            "category": "Cluster2",
            "keywords": ["c2", "test"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "p-c2-02",
            "proposed_rule": "Always isolate python virtual environments in sysadmin scripts before executing tools.",
            "category": "Cluster2",
            "keywords": ["c2", "test"],
        }, deduplicate=False)

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
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "ModCategory",
            "keywords": ["kw1", "kw2"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "p-mod-02",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "ModCategory",
            "keywords": ["kw1", "kw3"],
        }, deduplicate=False)

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


def test_compact_tui_active_mode_clustering_and_compact(tmp_path):
    """Verify active lesson duplicate clusters load and compact action updates db, lessons.md, and wiki."""
    db_path = str(tmp_path / "memory.db")
    lessons_md = str(tmp_path / "lessons.md")
    wiki_dir = str(tmp_path / "wiki")
    os.makedirs(wiki_dir, exist_ok=True)

    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "act-dup-01",
            "rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting"],
            "retrieval_count": 5,
            "prevented_rework_count": 2,
        })
        store.insert_lesson({
            "id": "act-dup-02",
            "rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting", "sc2086"],
            "retrieval_count": 3,
            "prevented_rework_count": 1,
        })
        from mcp_core.lessons_writer import write_all_lessons_to_markdown
        write_all_lessons_to_markdown(store.list_lessons(), lessons_md)

    async def _run():
        app = CompactQueueApp(
            db_path=db_path,
            min_cluster_size=2,
            mode="active",
            lessons_md=lessons_md,
            wiki_dir=wiki_dir,
        )
        async with app.run_test() as pilot:
            assert app.mode == "active"
            assert len(app.clusters) == 1
            cluster = app.clusters[0]
            assert cluster["primary_id"] == "act-dup-01"
            assert cluster["total_retrievals"] == 8
            assert cluster["total_prevented"] == 3

            # Execute compact
            app.action_compact()
            assert cluster["status"] == "compacted"

    asyncio.run(_run())

    with MemoryStore(db_path) as store:
        remaining = store.list_lessons()
        assert len(remaining) == 1
        primary = remaining[0]
        assert primary["id"] == "act-dup-01"
        assert primary["retrieval_count"] == 8
        assert primary["prevented_rework_count"] == 3

    # Check lessons.md updated
    content = open(lessons_md, encoding="utf-8").read()
    assert "act-dup-01" in content
    assert "act-dup-02" not in content

    # Check wiki index compiled
    index_path = os.path.join(wiki_dir, "index.md")
    assert os.path.exists(index_path)
    index_content = open(index_path, encoding="utf-8").read()
    assert "act-dup-01" in index_content
    assert "act-dup-02" not in index_content


def test_compact_tui_active_mode_discard(tmp_path):
    """Verify discarding an active cluster deletes all member lessons and updates lessons.md."""
    db_path = str(tmp_path / "memory.db")
    lessons_md = str(tmp_path / "lessons.md")
    wiki_dir = str(tmp_path / "wiki")
    os.makedirs(wiki_dir, exist_ok=True)

    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "act-disc-01",
            "rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting"],
        })
        store.insert_lesson({
            "id": "act-disc-02",
            "rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "ShellCheck",
            "keywords": ["bash", "quoting"],
        })
        from mcp_core.lessons_writer import write_all_lessons_to_markdown
        write_all_lessons_to_markdown(store.list_lessons(), lessons_md)

    async def _run():
        app = CompactQueueApp(
            db_path=db_path,
            min_cluster_size=2,
            mode="active",
            lessons_md=lessons_md,
            wiki_dir=wiki_dir,
        )
        async with app.run_test() as pilot:
            assert app.mode == "active"
            assert len(app.clusters) == 1
            app.action_discard()

    asyncio.run(_run())

    with MemoryStore(db_path) as store:
        assert len(store.list_lessons()) == 0

    content = open(lessons_md, encoding="utf-8").read()
    assert "act-disc-01" not in content
    assert "act-disc-02" not in content


def test_compact_tui_tab_switching(tmp_path):
    """Verify switching between pending and active cluster tabs."""
    db_path = str(tmp_path / "memory.db")
    lessons_md = str(tmp_path / "lessons.md")
    wiki_dir = str(tmp_path / "wiki")

    with MemoryStore(db_path) as store:
        # Seed 2 pending duplicates
        store.stage_pending_lesson({
            "id": "p-tab-01",
            "proposed_rule": "Deterministic binary isolation required across all environments.",
            "category": "Isolation",
            "keywords": ["binary"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "p-tab-02",
            "proposed_rule": "Deterministic binary isolation required across environments.",
            "category": "Isolation",
            "keywords": ["binary"],
        }, deduplicate=False)

        # Seed 2 active duplicates
        store.insert_lesson({
            "id": "a-tab-01",
            "rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "ShellCheck",
            "keywords": ["quoting"],
        })
        store.insert_lesson({
            "id": "a-tab-02",
            "rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "ShellCheck",
            "keywords": ["quoting"],
        })

    async def _run():
        app = CompactQueueApp(db_path=db_path, min_cluster_size=2, mode="pending", lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            assert app.mode == "pending"
            assert len(app.clusters) == 1
            assert app.clusters[0]["primary_id"] == "p-tab-01"

            # Switch to active via 't' key
            await pilot.press("t")
            assert app.mode == "active"
            assert len(app.clusters) == 1
            assert app.clusters[0]["primary_id"] == "a-tab-01"

            # Switch to sunset via 't' key
            await pilot.press("t")
            assert app.mode == "sunset"

            # Switch back to pending via 'tab' key
            await pilot.press("tab")
            assert app.mode == "pending"
            assert app.clusters[0]["primary_id"] == "p-tab-01"

    asyncio.run(_run())


def test_compact_tui_sunset_retirement(tmp_path):
    """Verify retiring a sunset candidate in the TUI via the 'x' key."""
    db_path = str(tmp_path / "memory.db")
    lessons_md = str(tmp_path / "lessons.md")
    wiki_dir = str(tmp_path / "wiki")

    with MemoryStore(db_path) as store:
        store.insert_lesson({
            "id": "sunset-tab-01",
            "rule": "Obsolete pattern that is constantly ineffective.",
            "category": "Testing",
            "keywords": ["pytest"],
            "retrieval_count": 2,
            "prevented_rework_count": 0,
            "ineffective_count": 10,
        })

    async def _run():
        app = CompactQueueApp(db_path=db_path, min_cluster_size=2, mode="sunset", lessons_md=lessons_md, wiki_dir=wiki_dir)
        async with app.run_test() as pilot:
            assert app.mode == "sunset"
            assert len(app.clusters) == 1
            assert app.clusters[0]["primary_id"] == "sunset-tab-01"
            assert app.clusters[0]["status"] == "pending"

            # Retire sunset candidate via 'x' key
            await pilot.press("x")
            assert app.clusters[0]["status"] == "retired"

    asyncio.run(_run())

    # Verify lesson was deleted from database
    with MemoryStore(db_path) as store:
        assert len(store.list_lessons()) == 0



def test_compact_queue_tui_cursor_advance_no_skip(temp_db):
    """Verify row highlighter advances to immediate next row without disappearing or skipping."""
    with MemoryStore(temp_db) as store:
        # Cluster 0
        store.stage_pending_lesson({
            "id": "p-adv-01",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting and globbing errors.",
            "category": "BashQuoting",
            "keywords": ["bash", "quoting"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "p-adv-02",
            "proposed_rule": "Always quote variables in bash scripts to avoid word splitting errors.",
            "category": "BashQuoting",
            "keywords": ["bash", "quoting"],
        }, deduplicate=False)
        # Cluster 1
        store.stage_pending_lesson({
            "id": "p-adv-03",
            "proposed_rule": "Deterministic binary isolation required across all environments and tools.",
            "category": "Isolation",
            "keywords": ["isolation", "binary"],
        }, deduplicate=False)
        store.stage_pending_lesson({
            "id": "p-adv-04",
            "proposed_rule": "Deterministic binary isolation required across environments and tools.",
            "category": "Isolation",
            "keywords": ["isolation", "binary"],
        }, deduplicate=False)

    async def _run():
        app = CompactQueueApp(db_path=temp_db, min_cluster_size=2)
        async with app.run_test() as pilot:
            assert len(app.clusters) == 2
            list_view = app.query_one("#cluster-list", ClusterListView)
            assert list_view.index == 0
            assert app.selected_cluster == app.clusters[0]

            # Execute compact on cluster 0
            app.action_compact()
            await pilot.pause()

            # Ensure index cleanly advanced to 1, not None and not skipping
            assert list_view.index == 1
            assert app.selected_cluster == app.clusters[1]
            assert app.clusters[0]["status"] == "compacted"
            assert app.clusters[1]["status"] == "pending"

    asyncio.run(_run())


