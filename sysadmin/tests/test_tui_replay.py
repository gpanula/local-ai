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
        assert (
            state.run_id == r["id"]
            or state.run_id in r.get("task_file", "")
            or (r.get("event_file") and state.run_id in r["event_file"])
        )
        assert state.current_stage == "finished"
        assert state.outcome in ("approved", "aborted", "failed", "complete")
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


def test_app_pilot_live_watch_mode():
    """Test mounting the Textual PipelineWatchApp in live watch mode (default)."""
    import asyncio
    from pipeline_tui.app import PipelineWatchApp

    async def _run():
        app = PipelineWatchApp(is_replay=False)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)

            # Check that app entered live watch mode and initialized widgets
            header = app.query_one("#header")
            assert header is not None
            thinking = app.query_one("#thinking-view")
            assert thinking is not None

            # Can quit with 'q'
            await pilot.press("q")

    asyncio.run(_run())


def test_app_pilot_stage_navigation_with_arrows():
    """Verify navigating stages with left and right arrow keys updates thinking and pillars."""
    import asyncio
    from pipeline_tui.app import PipelineWatchApp
    from textual.widgets import Static, TabbedContent

    async def _run():
        app = PipelineWatchApp(target_run_id="latest", is_replay=True)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)

            thinking_view = app.query_one("#thinking-view")
            header_widget = thinking_view.query_one("#thinking-header", Static)
            pillars_tabs = app.query_one("#pillars-tabs", TabbedContent)
            ctx_meter = app.query_one("#ctx-meter", Static)

            # Replay of latest ended at 'sysadmin' stage
            assert app.state.selected_stage == "sysadmin"
            assert "SYSADMIN" in str(ctx_meter.content)

            # Move left: sysadmin -> coder
            await pilot.press("left")
            assert app.state.selected_stage == "coder"
            assert "CODER" in str(header_widget.content)
            assert "CODER" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-code"

            # Move left: coder -> security
            await pilot.press("left")
            assert app.state.selected_stage == "security"
            assert "SECURITY" in str(header_widget.content)
            assert "SECURITY" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-risks"

            # Move left: security -> reviewer
            await pilot.press("left")
            assert app.state.selected_stage == "reviewer"
            assert "REVIEWER" in str(header_widget.content)
            assert "REVIEWER" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-critique"

            # Move left: reviewer -> orchestrator
            await pilot.press("left")
            assert app.state.selected_stage == "orchestrator"
            assert "ORCHESTRATOR" in str(header_widget.content)
            assert "ORCHESTRATOR" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-strategy"

            # Move left: orchestrator -> architect
            await pilot.press("left")
            assert app.state.selected_stage == "architect"
            assert "ARCHITECT" in str(header_widget.content)
            assert "ARCHITECT" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-strategy"

            # Bound check: left again shouldn't go past architect
            await pilot.press("left")
            assert app.state.selected_stage == "architect"

            # Move right: architect -> orchestrator
            await pilot.press("right")
            assert app.state.selected_stage == "orchestrator"
            assert "ORCHESTRATOR" in str(header_widget.content)
            assert "ORCHESTRATOR" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-strategy"

            # Move right: orchestrator -> reviewer
            await pilot.press("right")
            assert app.state.selected_stage == "reviewer"
            assert "REVIEWER" in str(header_widget.content)
            assert "REVIEWER" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-critique"

            # Move right: reviewer -> security
            await pilot.press("right")
            assert app.state.selected_stage == "security"
            assert "SECURITY" in str(header_widget.content)
            assert "SECURITY" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-risks"

            # Move right: security -> coder
            await pilot.press("right")
            assert app.state.selected_stage == "coder"
            assert "CODER" in str(header_widget.content)
            assert "CODER" in str(ctx_meter.content)
            assert pillars_tabs.active == "tab-code"

            # Move right: coder -> sysadmin
            await pilot.press("right")
            assert app.state.selected_stage == "sysadmin"
            assert "SYSADMIN" in str(header_widget.content)
            assert "SYSADMIN" in str(ctx_meter.content)

            # Bound check: right again shouldn't go past sysadmin
            await pilot.press("right")
            assert app.state.selected_stage == "sysadmin"

            # Navigate back left to coder
            await pilot.press("left")
            assert app.state.selected_stage == "coder"
            assert "CODER" in str(ctx_meter.content)

            await pilot.press("q")

    asyncio.run(_run())


def test_app_pilot_stage_mouse_click_selection():
    """Verify that clicking stage badges in the stepper updates the selected stage and view."""
    import asyncio
    from textual.widgets import Static
    from pipeline_tui.app import PipelineWatchApp

    async def _run():
        app = PipelineWatchApp(target_run_id="latest", is_replay=True)
        async with app.run_test(size=(140, 35)) as pilot:
            await pilot.pause(0.1)
            thinking_view = app.query_one("#thinking-view")
            header_widget = thinking_view.query_one("#thinking-header", Static)

            stages_to_test = ["orchestrator", "security", "coder", "sysadmin", "architect", "reviewer"]
            for stage in stages_to_test:
                badge = app.query_one(f"#stage-badge-{stage}")
                await pilot.click(badge)
                assert app.state.selected_stage == stage
                assert stage.upper() in str(header_widget.content)

            await pilot.press("q")

    asyncio.run(_run())



def test_arc_orc_rev_live_event_stream_tracking():
    """Verify live Arc-Orc-Rev pipeline transitions update stepper, thinking, context, and terminal."""
    import asyncio
    from pipeline_tui.app import PipelineWatchApp
    from textual.widgets import Static

    async def _run():
        app = PipelineWatchApp(is_replay=False)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)

            stepper = app.query_one("#stepper")
            thinking_view = app.query_one("#thinking-view")
            ctx_meter = app.query_one("#ctx-meter")
            term_drawer = app.query_one("#terminal-drawer")

            # 1. Pipeline start
            app.state.handle_event({"type": "pipeline_start", "data": {"task_file": "test.md", "prompt": "build hello world"}})
            app._apply_single_event_ui({"type": "pipeline_start"})

            # 2. Stage: Architect
            app.state.handle_event({"type": "stage_transition", "data": {"stage": "architect", "iteration": 1}})
            app._apply_single_event_ui({"type": "stage_transition"})
            assert app.state.current_stage == "architect"
            assert app.state.selected_stage == "architect"

            # Check Stepper display includes Architect as stage 1 with in-progress badge
            stepper_text = str(stepper.query_one("#stepper-content", Static).content)
            assert "Architect" in stepper_text
            assert "⟳ Architect" in stepper_text

            # Emit architect thinking
            app.state.handle_event({
                "type": "thinking_chunk",
                "data": {"stage": "architect", "chunk": "Decomposing hello world architecture...", "model": "winter-prime"},
            })
            app._apply_single_event_ui({"type": "thinking_chunk", "data": {"stage": "architect"}})
            thinking_body = str(thinking_view.query_one("#thinking-body", Static).content)
            assert "Decomposing hello world" in thinking_body

            # Emit architect context window
            app.state.handle_event({
                "type": "context_window",
                "data": {"stage": "architect", "user_prompt": "build hello world", "token_breakdown": {"total": 1200, "limit": 8192}},
            })
            app._apply_single_event_ui({"type": "context_window", "data": {"stage": "architect"}})
            assert "ARCHITECT" in str(ctx_meter.content)
            assert "1,200" in str(ctx_meter.content)

            # 3. Stage: Orchestrator
            app.state.handle_event({"type": "stage_transition", "data": {"stage": "orchestrator", "iteration": 1}})
            app._apply_single_event_ui({"type": "stage_transition"})
            assert app.state.current_stage == "orchestrator"
            stepper_text = str(stepper.query_one("#stepper-content", Static).content)
            assert "✓ Architect" in stepper_text
            assert "⟳ Orchestrator" in stepper_text

            # 4. Stage: Reviewer
            app.state.handle_event({"type": "stage_transition", "data": {"stage": "reviewer", "iteration": 1}})
            app._apply_single_event_ui({"type": "stage_transition"})
            stepper_text = str(stepper.query_one("#stepper-content", Static).content)
            assert "✓ Architect" in stepper_text
            assert "✓ Orchestrator" in stepper_text
            assert "⟳ Reviewer" in stepper_text

            # 5. Stage: Security
            app.state.handle_event({"type": "stage_transition", "data": {"stage": "security", "iteration": 1}})
            app._apply_single_event_ui({"type": "stage_transition"})
            stepper_text = str(stepper.query_one("#stepper-content", Static).content)
            assert "✓ Reviewer" in stepper_text
            assert "⟳ Security" in stepper_text

            # 6. Stage: Coder
            app.state.handle_event({"type": "stage_transition", "data": {"stage": "coder", "iteration": 1}})
            app._apply_single_event_ui({"type": "stage_transition"})
            stepper_text = str(stepper.query_one("#stepper-content", Static).content)
            assert "✓ Security" in stepper_text
            assert "⟳ Coder" in stepper_text

            # 7. Stage: Sysadmin
            app.state.handle_event({"type": "stage_transition", "data": {"stage": "sysadmin", "iteration": 1}})
            app._apply_single_event_ui({"type": "stage_transition"})
            stepper_text = str(stepper.query_one("#stepper-content", Static).content)
            assert "✓ Coder" in stepper_text
            assert "⟳ Sysadmin" in stepper_text

            # Terminal output streamed during dispatch / sysadmin
            app.state.handle_event({"type": "terminal_chunk", "data": {"text": "Executing: echo 'hello world'"}})
            app._apply_single_event_ui({"type": "terminal_chunk", "data": {"text": "Executing: echo 'hello world'"}})
            assert term_drawer.line_count == 1

            # 8. Pipeline complete
            app.state.handle_event({"type": "pipeline_end", "data": {"outcome": "complete"}})
            app._apply_single_event_ui({"type": "pipeline_end"})
            stepper_text = str(stepper.query_one("#stepper-content", Static).content)
            assert "✓ Sysadmin" in stepper_text

            await pilot.press("q")

    asyncio.run(_run())
