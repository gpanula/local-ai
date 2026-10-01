"""CLI argument parser and entrypoint for PipelineWatch."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from rich.console import Console
from rich.table import Table

from pipeline_tui.app import PipelineWatchApp
from pipeline_tui.discovery import find_run, list_runs


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline-watch",
        description="Standalone TUI observer for monitoring and replaying local AI pipeline runs.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available recent pipeline runs and exit.",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Max number of runs to list (default: 20).",
    )
    parser.add_argument(
        "--replay",
        metavar="TARGET",
        nargs="?",
        const="latest",
        help="Replay a run by exact ID, short prefix, keyword, or 'latest'.",
    )
    parser.add_argument(
        "--run",
        dest="run_id",
        help="Watch or view a specific run ID.",
    )
    parser.add_argument(
        "--file",
        dest="event_file",
        help="Watch a specific JSONL event file.",
    )

    args = parser.parse_args(argv)

    if args.list:
        runs = list_runs(limit=args.limit)
        console = Console()
        if not runs:
            console.print("[yellow]No recorded pipeline runs found.[/yellow]")
            return 0

        table = Table(title="📜 Recent Pipeline Runs", header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("Run ID", style="bold yellow")
        table.add_column("Timestamp", style="dim")
        table.add_column("Outcome")
        table.add_column("Model", style="green")
        table.add_column("Task Prompt")

        for idx, run in enumerate(runs, start=1):
            outcome = run.get("outcome", "").upper()
            out_style = "bold green" if "APPROV" in outcome else ("bold red" if "FAIL" in outcome else "yellow")
            prompt = (run.get("prompt") or run.get("task_file") or "").replace("\n", " ")[:50]
            table.add_row(
                str(idx),
                run.get("id", ""),
                run.get("timestamp", "")[:19].replace("T", " "),
                f"[{out_style}]{outcome}[/{out_style}]",
                run.get("model", ""),
                prompt,
            )

        console.print(table)
        return 0

    target_id = args.replay or args.run_id
    is_replay = bool(args.replay)

    app = PipelineWatchApp(
        target_run_id=target_id,
        event_file=args.event_file,
        is_replay=is_replay,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
