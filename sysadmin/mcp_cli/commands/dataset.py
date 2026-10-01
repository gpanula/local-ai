"""Dataset export command for fine-tuning Local AI models."""

import os
from mcp_cli.base import BaseCommand, command
from mcp_core.dataset import (
    DEFAULT_DATASET_OUTPUT_DIR,
    DEFAULT_TRAJECTORIES_PATH,
    export_datasets,
)


@command
class ExportDatasetCommand(BaseCommand):
    name = "export-dataset"
    help = "Export pipeline trajectory logs into fine-tuning datasets (DPO & SFT JSONL)"

    def register_args(self, parser):
        parser.add_argument(
            "--input",
            default=DEFAULT_TRAJECTORIES_PATH,
            help=f"Path to input trajectories.jsonl file (default: {DEFAULT_TRAJECTORIES_PATH})",
        )
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_DATASET_OUTPUT_DIR,
            help=f"Directory to save output datasets (default: {DEFAULT_DATASET_OUTPUT_DIR})",
        )
        parser.add_argument(
            "--format",
            choices=["dpo", "sft_multiturn", "sft_direct", "all"],
            default="all",
            help="Dataset format to export (default: all)",
        )
        parser.add_argument(
            "--all-outcomes",
            action="store_true",
            help="Include failed/aborted trajectories in addition to approved ones",
        )
        parser.add_argument(
            "--include-synthetic",
            action="store_true",
            help="Include synthetic lesson exemplars synthesized from lessons.md",
        )
        parser.add_argument(
            "--no-cot",
            action="store_true",
            help="Exclude Chain-of-Thought reasoning (Analysis & Strategy, Risks) from exported completions",
        )
        parser.add_argument(
            "--role",
            choices=["coder", "orchestrator", "reviewer", "security", "sysadmin", "architect"],
            default="coder",
            help="Target role for Chain-of-Thought dataset export (default: coder)",
        )

    def run(self, args):
        input_path = args.input
        output_dir = args.output_dir
        format_type = args.format
        approved_only = not args.all_outcomes
        include_synthetic = getattr(args, "include_synthetic", False)
        include_cot = not getattr(args, "no_cot", False)
        target_role = getattr(args, "role", "coder")

        if not os.path.exists(input_path):
            print(f"❌ Trajectory file not found at '{input_path}'. Run pipeline tasks with rework to generate training data.")
            return

        formats = [format_type] if format_type != "all" else ["dpo", "sft_multiturn", "sft_direct"]
        print("=" * 60)
        print("🚀 Local AI Dataset Exporter")
        print("=" * 60)
        print(f"  Input:        {input_path}")
        print(f"  Output Dir:   {output_dir}")
        print(f"  Filter:       {'Approved runs only' if approved_only else 'All outcomes'}")
        print(f"  Synthetic:    {'Included' if include_synthetic else 'Excluded'}")
        print(f"  Role:         {target_role}")
        print(f"  Reasoning:    {'Chain-of-Thought (CoT) enabled' if include_cot else 'Code-only'}")
        print("-" * 60)

        counts = export_datasets(
            trajectories_path=input_path,
            output_dir=output_dir,
            formats=formats,
            approved_only=approved_only,
            include_synthetic_lessons=include_synthetic,
            role=target_role,
            include_cot=include_cot,
        )

        total_exported = sum(counts.values())
        for fmt, cnt in counts.items():
            filename = f"{fmt}_dataset.jsonl"
            print(f"  ✅ {fmt:15s}: {cnt:3d} sample(s) -> {os.path.join(output_dir, filename)}")

        print("=" * 60)
        if total_exported > 0:
            print(f"🎉 Successfully exported {total_exported} training sample(s) across {len(counts)} format(s).")
        else:
            print("ℹ️ No valid training samples found matching criteria (e.g. requires multi-iteration rework).")
