"""Unit tests for PipelineWatch state and replay parsing."""

import pytest

from pipeline_tui.discovery import find_run, list_runs, load_events_for_run
from pipeline_tui.state import PipelineState


def test_real_trajectories_replay_into_state():
    """Verify that all existing historical trajectories in workspace load cleanly into state."""
    runs = list_runs(limit=10)
    assert len(runs) > 0

    for r in runs:
        events = load_events_for_run(r)
        assert len(events) > 0

        state = PipelineState()
        for evt in events:
            state.handle_event(evt)

        # Basic integrity checks on accumulated state
        assert state.run_id == r["id"]
        assert state.current_stage == "finished"
        assert state.outcome in ("approved", "aborted", "failed")
        assert len(state.iterations) >= 1

        cur_it = state.current_iteration()
        # Context window reconstructed
        assert "token_breakdown" in cur_it.context_window
        assert cur_it.context_window["token_breakdown"]["total"] > 0

        # Code or reasoning present
        assert cur_it.code or cur_it.reasoning or cur_it.thinking


def test_pipeline_state_iteration_stepping():
    """Test switching iterations and verifying iteration state isolation."""
    state = PipelineState()
    state.handle_event({"type": "stage_transition", "data": {"stage": "author", "iteration": 1}})
    state.handle_event({"type": "code_synthesized", "data": {"iteration": 1, "code": "echo v1"}})

    state.handle_event({"type": "stage_transition", "data": {"stage": "author", "iteration": 2}})
    state.handle_event({"type": "code_synthesized", "data": {"iteration": 2, "code": "echo v2"}})

    assert state.active_iteration_idx == 2
    assert state.get_iteration(1).code == "echo v1"
    assert state.get_iteration(2).code == "echo v2"
    assert state.current_iteration().code == "echo v2"

    state.active_iteration_idx = 1
    assert state.current_iteration().code == "echo v1"


def test_app_pilot_replay_and_toggles():
    """Test mounting the Textual PipelineWatchApp in headless test mode and pressing keys."""
    import asyncio
    from pipeline_tui.app import PipelineWatchApp

    async def _run():
        app = PipelineWatchApp(target_run_id="latest", is_replay=True)
        async with app.run_test() as pilot:
            # Give on_mount time to process
            await pilot.pause(0.1)

            # Check widgets mounted
            assert app.query_one("#header") is not None
            assert app.query_one("#stepper") is not None
            assert app.query_one("#thinking-view") is not None
            assert app.query_one("#pillars-view") is not None
            assert app.query_one("#context-drawer") is not None
            assert app.query_one("#terminal-drawer") is not None

            # Test toggle context drawer ('c')
            ctx = app.query_one("#context-drawer")
            assert not ctx.is_collapsed
            await pilot.press("c")
            assert ctx.is_collapsed
            await pilot.press("c")
            assert not ctx.is_collapsed

            # Test toggle terminal drawer ('t')
            term = app.query_one("#terminal-drawer")
            assert term.mode_index == 1
            await pilot.press("t")
            assert term.mode_index == 2  # compact

            # Test follow terminal ('f')
            await pilot.press("f")
            assert term.auto_scroll is True

            # Quit app ('q')
            await pilot.press("q")

    asyncio.run(_run())
