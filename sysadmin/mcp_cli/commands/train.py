"""Fine-tune Winter Multi-Agent Models command with live terminal-mcp streaming."""

import os
import subprocess
import sys

os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

from mcp_cli.base import BaseCommand, command
from mcp_core.dataset import export_datasets
from mcp_core.transport import send_terminal_mcp
from mcp_core.workspace import WORKSPACE_ROOT


@command
class TrainCommand(BaseCommand):
    name = "train"
    help = "Fine-tune Winter Multi-Agent models on lessons and trajectories with live terminal streaming"

    def register_args(self, parser):
        parser.add_argument(
            "--role", "-r",
            choices=["coder", "orchestrator", "reviewer", "sysadmin", "architect", "security"],
            default="coder",
            help="Winter agent role to fine-tune (default: coder)",
        )
        parser.add_argument(
            "--tier", "-t",
            choices=["8gb", "16gb", "24gb"],
            default="8gb",
            help="Hardware tier to target (default: 8gb)",
        )
        parser.add_argument(
            "--method", "-m",
            choices=["dpo", "sft"],
            default="dpo",
            help="Training methodology (default: dpo)",
        )
        parser.add_argument(
            "--epochs", "-e",
            type=int,
            default=3,
            help="Number of training epochs (default: 3)",
        )
        parser.add_argument(
            "--lr",
            type=float,
            default=5e-5,
            help="Learning rate (default: 5e-5)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1,
            help="Per-device batch size (default: 1)",
        )
        parser.add_argument(
            "--grad-accum",
            type=int,
            default=4,
            help="Gradient accumulation steps (default: 4)",
        )
        parser.add_argument(
            "--alias-active",
            action="store_true",
            help="Automatically alias trained model to active role tag (e.g. winter-coder:8gb)",
        )
        parser.add_argument(
            "--full-model",
            action="store_true",
            help="Download and train on full unquantized FP16 base model instead of default 4-bit pre-quantized",
        )
        parser.add_argument(
            "--cache-dir",
            default=None,
            help="Custom directory for downloading Hugging Face models",
        )
        parser.add_argument(
            "--skip-setup",
            action="store_true",
            help="Skip automatic train_venv setup check",
        )

    def _ensure_train_venv(self) -> str:
        train_venv = os.path.join(WORKSPACE_ROOT, "sysadmin", "train_venv")
        train_python = os.path.join(train_venv, "bin", "python3")

        if not os.path.exists(train_python):
            send_terminal_mcp("📦 Training environment missing. Running `sysadmin/setup_train_env.sh`...")
            setup_script = os.path.join(WORKSPACE_ROOT, "sysadmin", "setup_train_env.sh")
            res = subprocess.run(["bash", setup_script], text=True)
            if res.returncode != 0:
                send_terminal_mcp("❌ [ERROR] Failed to set up training environment.")
                raise SystemExit(1)

        return train_python

    def run(self, args):
        send_terminal_mcp("==============================================================================")
        send_terminal_mcp(f"🎓 Winter Fine-Tuning Pipeline: winter-{args.role}:{args.tier}")
        send_terminal_mcp("==============================================================================")

        # 1. Ensure training environment
        if not args.skip_setup:
            train_python = self._ensure_train_venv()
        else:
            train_python = os.path.join(WORKSPACE_ROOT, "sysadmin", "train_venv", "bin", "python3")

        # 2. Export & augment datasets from lessons
        send_terminal_mcp("📊 Preparing training dataset from lessons & trajectories...")
        counts = export_datasets(formats=[args.method], include_synthetic_lessons=True, role=args.role)
        send_terminal_mcp(f"  ✓ Exported dataset samples: {counts.get(args.method, 0):,} records ({args.method.upper()})")

        # 3. Launch training script inside train_venv
        train_script = os.path.join(WORKSPACE_ROOT, "sysadmin", "train_local_model.py")
        cmd = [
            train_python,
            train_script,
            "--role", args.role,
            "--tier", args.tier,
            "--method", args.method,
            "--epochs", str(args.epochs),
            "--lr", str(args.lr),
            "--batch-size", str(args.batch_size),
            "--grad-accum", str(args.grad_accum),
        ]
        if args.alias_active:
            cmd.append("--alias-active")
        if args.full_model:
            cmd.append("--full-model")
        cache_dir = args.cache_dir or os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "hf_cache")
        os.environ["HF_HOME"] = cache_dir
        cmd.extend(["--cache-dir", cache_dir])

        res = subprocess.run(cmd, text=True)
        if res.returncode != 0:
            send_terminal_mcp(f"❌ [ERROR] Training failed with exit code {res.returncode}.")
            raise SystemExit(1)

        send_terminal_mcp("==============================================================================")
        send_terminal_mcp(f"🎉 Model `winter-{args.role}:{args.tier}-trained` successfully trained & registered!")
        send_terminal_mcp("==============================================================================")
