"""Build Winter Customized Ollama Models with live terminal-mcp streaming."""

import os
import shutil
import subprocess
from typing import List, Tuple

from mcp_cli.base import BaseCommand, command
from mcp_core.transport import send_terminal_mcp
from mcp_core.workspace import WORKSPACE_ROOT


# Model definitions: (tier_dir, modelfile_name, variant_tag, alias_tag)
MODEL_SPECS = {
    "8gb": [
        ("8gb", "Modelfile-orchestrator-deepseek8b", "winter-orchestrator:8gb-deepseek", "winter-orchestrator:8gb"),
        ("8gb", "Modelfile-architect-qwen7b", "winter-architect:8gb-qwen", "winter-architect:8gb"),
        ("8gb", "Modelfile-coder-qwen7b", "winter-coder:8gb-qwen", "winter-coder:8gb"),
        ("8gb", "Modelfile-sysadmin-qwen7b", "winter-sysadmin:8gb-qwen", "winter-sysadmin:8gb"),
        ("8gb", "Modelfile-security-deepseek8b", "winter-security:8gb-deepseek", "winter-security:8gb"),
        ("8gb", "Modelfile-reviewer-qwen8b", "winter-reviewer:8gb-qwen", "winter-reviewer:8gb"),
    ],
    "16gb": [
        ("16gb", "Modelfile-orchestrator-deepseek16b", "winter-orchestrator:16gb-deepseek", "winter-orchestrator:16gb"),
        ("16gb", "Modelfile-architect-deepseek16b", "winter-architect:16gb-deepseek", "winter-architect:16gb"),
        ("16gb", "Modelfile-coder-qwen14b", "winter-coder:16gb-qwen", "winter-coder:16gb"),
        ("16gb", "Modelfile-sysadmin-qwen14b", "winter-sysadmin:16gb-qwen", "winter-sysadmin:16gb"),
        ("16gb", "Modelfile-security-deepseek16b", "winter-security:16gb-deepseek", "winter-security:16gb"),
        ("16gb", "Modelfile-reviewer-deepseek16b", "winter-reviewer:16gb-deepseek", "winter-reviewer:16gb"),
    ],
    "24gb": [
        ("24gb", "Modelfile-orchestrator-qwen32b", "winter-orchestrator:24gb-qwen", "winter-orchestrator:24gb"),
        ("24gb", "Modelfile-architect-qwen32b", "winter-architect:24gb-qwen", "winter-architect:24gb"),
        ("24gb", "Modelfile-coder-qwen32b", "winter-coder:24gb-qwen", "winter-coder:24gb"),
        ("24gb", "Modelfile-sysadmin-codestral", "winter-sysadmin:24gb-codestral", "winter-sysadmin:24gb"),
        ("24gb", "Modelfile-security-codestral", "winter-security:24gb-codestral", "winter-security:24gb"),
        ("24gb", "Modelfile-reviewer-codestral", "winter-reviewer:24gb-codestral", "winter-reviewer:24gb"),
    ],
}


@command
class BuildModelsCommand(BaseCommand):
    name = "build-models"
    help = "Build and tag customized Winter Ollama models across tiers with live terminal streaming"

    def register_args(self, parser):
        parser.add_argument(
            "tier",
            nargs="?",
            choices=["8gb", "16gb", "24gb", "all", "list"],
            default="all",
            help="Tier to build: 8gb, 16gb, 24gb, all, or list (default: all)",
        )
        parser.add_argument(
            "--trained",
            action="store_true",
            help="Build and tag fine-tuned trained models (Modelfile-*-trained)",
        )

    def _build_one(self, tier_dir: str, modelfile: str, variant_tag: str, alias_tag: str) -> bool:
        base_dir = os.path.join(WORKSPACE_ROOT, "ollama_update", "customized_models", tier_dir)
        modelfile_path = os.path.join(base_dir, modelfile)

        if not os.path.isfile(modelfile_path):
            send_terminal_mcp(f"❌ [ERROR] Modelfile not found: {modelfile_path}")
            return False

        send_terminal_mcp("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        send_terminal_mcp(f"🔨 Building {variant_tag} (from {tier_dir}/{modelfile})...")
        send_terminal_mcp("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Check if modelfile contains an ADAPTER instruction to ensure native GGUF conversion
        try:
            content_changed = False
            updated_lines = []
            with open(modelfile_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("ADAPTER"):
                        adapter_target = line.strip().split(maxsplit=1)[1].strip()
                        if adapter_target.endswith((".gguf", ".safetensors", ".bin")):
                            adapter_dir = os.path.dirname(adapter_target)
                        else:
                            adapter_dir = adapter_target
                        gguf_file = os.path.join(adapter_dir, "adapter.gguf")
                        if not os.path.isfile(gguf_file):
                            train_python = os.path.join(WORKSPACE_ROOT, "sysadmin", "train_venv", "bin", "python3")
                            if os.path.isfile(train_python):
                                subprocess.run(
                                    [train_python, "-c", f"from mcp_core.trainer import export_lora_to_gguf; export_lora_to_gguf('{adapter_dir}')"],
                                    env=dict(os.environ, PYTHONPATH=os.path.join(WORKSPACE_ROOT, "sysadmin")),
                                    capture_output=True,
                                )
                        if os.path.isfile(gguf_file) and adapter_target != gguf_file:
                            updated_lines.append(f"ADAPTER {gguf_file}\n")
                            content_changed = True
                            continue
                    updated_lines.append(line)
            if content_changed:
                with open(modelfile_path, "w", encoding="utf-8") as f:
                    f.writelines(updated_lines)
        except Exception:
            pass

        proc = subprocess.run(
            ["ollama", "create", variant_tag, "-f", modelfile],
            cwd=base_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            send_terminal_mcp(f"❌ [ERROR] Failed to build {variant_tag}:\n{proc.stderr}")
            return False

        if alias_tag and alias_tag != variant_tag:
            send_terminal_mcp(f"🏷️  Aliasing {variant_tag} -> {alias_tag}...")
            cp_proc = subprocess.run(
                ["ollama", "cp", variant_tag, alias_tag],
                capture_output=True,
                text=True,
            )
            if cp_proc.returncode != 0:
                send_terminal_mcp(f"⚠️ [WARNING] Failed to alias {variant_tag} -> {alias_tag}:\n{cp_proc.stderr}")
                return False

        send_terminal_mcp(f"✅ Successfully built and tagged {variant_tag}\n")
        return True

    def run(self, args):
        if args.tier == "list":
            send_terminal_mcp("Winter Multi-Agent Model Matrix (6 Roles x 3 Tiers):")
            for tier, models in MODEL_SPECS.items():
                send_terminal_mcp(f"\n📦 {tier.upper()} Tier:")
                for _, _, variant, alias in models:
                    send_terminal_mcp(f"  • {variant} -> {alias}")
            return

        tiers_to_build = ["8gb", "16gb", "24gb"] if args.tier == "all" else [args.tier]

        send_terminal_mcp("==============================================================================")
        send_terminal_mcp(f"🏗️  Building Winter Multi-Agent Models (Tier: {args.tier}, Mode: {'Trained LoRA' if args.trained else 'Standard'})")
        send_terminal_mcp("==============================================================================")

        total_built = 0
        total_failed = 0

        for tier in tiers_to_build:
            send_terminal_mcp(f"\n🚀 [Building {tier.upper()} Tier Models]")
            if args.trained:
                tier_dir = os.path.join(WORKSPACE_ROOT, "ollama_update", "customized_models", tier)
                trained_files = [f for f in os.listdir(tier_dir) if f.startswith("Modelfile-") and f.endswith("-trained")]
                if not trained_files:
                    send_terminal_mcp(f"ℹ️  No trained modelfiles found in `{tier}` tier.")
                    continue
                for tf in trained_files:
                    # e.g. Modelfile-coder-trained -> role = coder
                    role = tf.replace("Modelfile-", "").replace("-trained", "")
                    variant = f"winter-{role}:{tier}-trained"
                    ok = self._build_one(tier, tf, variant, alias_tag="")
                    if ok:
                        total_built += 1
                    else:
                        total_failed += 1
            else:
                for tier_dir, modelfile, variant_tag, alias_tag in MODEL_SPECS[tier]:
                    ok = self._build_one(tier_dir, modelfile, variant_tag, alias_tag)
                    if ok:
                        total_built += 1
                    else:
                        total_failed += 1

        send_terminal_mcp("==============================================================================")
        if total_failed == 0:
            send_terminal_mcp(f"🎉 Successfully built all {total_built} model(s) across {len(tiers_to_build)} tier(s)!")
            send_terminal_mcp("==============================================================================")
        else:
            send_terminal_mcp(f"❌ [BUILD FAILED] {total_failed} model(s) failed to build ({total_built} succeeded).")
            send_terminal_mcp("==============================================================================")
            raise SystemExit(1)
