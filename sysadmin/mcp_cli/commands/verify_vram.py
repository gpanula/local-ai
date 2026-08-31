"""VRAM Residency & GPU Offload Audit Command with live terminal-mcp streaming."""

import json
import os
import subprocess
import time
import urllib.request
from typing import Any, Dict, List, Optional

from mcp_cli.base import BaseCommand, command
from mcp_core.transport import send_terminal_mcp
from mcp_core.hardware import get_default_model


@command
class VerifyVramCommand(BaseCommand):
    name = "verify-vram"
    help = "Verify if models fit 100% in GPU VRAM or if layers/KV-cache offload to CPU/RAM"

    def register_args(self, parser):
        parser.add_argument(
            "--tier", "-t",
            choices=["8gb", "16gb", "24gb", "all"],
            default="24gb",
            help="Model tier to verify (default: 24gb)",
        )
        parser.add_argument(
            "model_name",
            nargs="?",
            default=None,
            help="Optional specific model name to audit (e.g. winter-coder:24gb)",
        )
        parser.add_argument(
            "--host",
            default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            help="Ollama host URL (default: http://127.0.0.1:11434)",
        )

    def _unload_models(self, host: str, models: List[str]) -> None:
        """Unload active models from VRAM."""
        for m in models:
            try:
                req = urllib.request.Request(
                    f"{host.rstrip('/')}/api/generate",
                    data=json.dumps({"model": m, "keep_alive": 0}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except Exception:
                pass

    def _get_gpu_info(self) -> Dict[str, Any]:
        """Query nvidia-smi for total and used VRAM."""
        try:
            name_proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, check=True, timeout=5,
            )
            vram_proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=5,
            )
            gpu_name = name_proc.stdout.strip().splitlines()[0]
            parts = vram_proc.stdout.strip().splitlines()[0].split(",")
            total_mb = int(parts[0].strip())
            used_mb = int(parts[1].strip())
            return {"name": gpu_name, "total_mb": total_mb, "used_mb": used_mb, "available": True}
        except Exception:
            return {"name": "Host GPU (via Ollama API)", "total_mb": 24576, "used_mb": 0, "available": False}

    def _warmup_model(self, host: str, model_name: str) -> Optional[Dict[str, Any]]:
        """Warm up model and return generation telemetry (tps, tokens, duration)."""
        start = time.perf_counter()
        try:
            req = urllib.request.Request(
                f"{host.rstrip('/')}/api/generate",
                data=json.dumps({
                    "model": model_name,
                    "prompt": "Write a short 3-line bash script that prints hello.",
                    "stream": False,
                    "keep_alive": "5m",
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "error" in data:
                    return None

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            eval_count = data.get("eval_count", 0)
            eval_duration_ns = data.get("eval_duration", 0)
            eval_sec = eval_duration_ns / 1e9 if eval_duration_ns > 0 else (elapsed_ms / 1000.0)
            tps = (eval_count / eval_sec) if eval_sec > 0 else 0.0

            return {
                "elapsed_ms": elapsed_ms,
                "eval_count": eval_count,
                "eval_sec": eval_sec,
                "tps": tps,
            }
        except Exception:
            return None

    def _get_active_model_ps(self, host: str, target_model: str) -> Optional[dict]:
        """Query /api/ps and find target model record."""
        try:
            req = urllib.request.Request(f"{host.rstrip('/')}/api/ps")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("models", []):
                    if m.get("name") == target_model or m.get("model") == target_model:
                        return m
        except Exception:
            pass
        return None

    def run(self, args):
        host = args.host.rstrip("/")
        if not host.startswith("http"):
            host = f"http://{host}"

        if args.model_name:
            models_to_test = [args.model_name]
        elif args.tier == "8gb":
            models_to_test = ["winter-orchestrator:8gb", "winter-coder:8gb", "winter-reviewer:8gb"]
        elif args.tier == "16gb":
            models_to_test = ["winter-orchestrator:16gb", "winter-coder:16gb", "winter-reviewer:16gb"]
        elif args.tier == "24gb":
            models_to_test = ["winter-orchestrator:24gb", "winter-coder:24gb", "winter-reviewer:24gb"]
        else:
            models_to_test = [
                "winter-orchestrator:8gb", "winter-coder:8gb", "winter-reviewer:8gb",
                "winter-orchestrator:16gb", "winter-coder:16gb", "winter-reviewer:16gb",
                "winter-orchestrator:24gb", "winter-coder:24gb", "winter-reviewer:24gb",
            ]

        send_terminal_mcp("==============================================================================")
        send_terminal_mcp("🔍 GPU VRAM Residency & CPU Offload Audit")
        send_terminal_mcp("==============================================================================")
        send_terminal_mcp(f"  Ollama Host: {host}")
        send_terminal_mcp(f"  Models:      {', '.join(models_to_test)}")
        send_terminal_mcp("------------------------------------------------------------------------------")

        gpu_info = self._get_gpu_info()
        send_terminal_mcp(f"  GPU Device:  {gpu_info['name']}")
        send_terminal_mcp(f"  Total VRAM:  {gpu_info['total_mb']} MB")
        if gpu_info["available"]:
            send_terminal_mcp(f"  Used (Cold): {gpu_info['used_mb']} MB")
        send_terminal_mcp("==============================================================================")

        audit_failed = False

        try:
            for target_model in models_to_test:
                send_terminal_mcp(f"\n▶️ Testing model: {target_model}")
                self._unload_models(host, models_to_test)
                time.sleep(1)

                warmup = self._warmup_model(host, target_model)
                if warmup is None:
                    send_terminal_mcp(f"❌ [ERROR] Failed to warm up model '{target_model}'. Check if model is pulled.")
                    audit_failed = True
                    continue

                ps_info = self._get_active_model_ps(host, target_model)
                if not ps_info:
                    send_terminal_mcp(f"⚠️ [WARNING] Model '{target_model}' was not found in active /api/ps list.")
                    audit_failed = True
                    continue

                size_bytes = ps_info.get("size", 0)
                size_vram_bytes = ps_info.get("size_vram", 0)
                context_length = ps_info.get("context_length", 0)

                size_mb = size_bytes / (1024 * 1024)
                size_vram_mb = size_vram_bytes / (1024 * 1024)
                spill_mb = max(0.0, size_mb - size_vram_mb)
                offload_pct = (spill_mb / size_mb * 100) if size_mb > 0 else 0.0

                if size_vram_bytes >= size_bytes:
                    processor = "100% GPU"
                elif size_vram_bytes == 0:
                    processor = "100% CPU"
                else:
                    gpu_pct = (size_vram_bytes / size_bytes) * 100
                    processor = f"{gpu_pct:.1f}% GPU / {100.0 - gpu_pct:.1f}% CPU"

                # Speed badge
                tps = warmup["tps"]
                if tps < 26.0:
                    tps_str = f"🚨 {tps:.1f} t/s (CRITICAL LOW)"
                elif tps < 51.0:
                    tps_str = f"⚠️ {tps:.1f} t/s"
                else:
                    tps_str = f"{tps:.1f} t/s"

                live_gpu = self._get_gpu_info()
                free_vram_mb = max(0, gpu_info["total_mb"] - live_gpu["used_mb"]) if live_gpu["available"] else max(0, int(gpu_info["total_mb"] - size_vram_mb))

                send_terminal_mcp(
                    f"  📊 Model: {target_model} | Context: {context_length:,} tokens | Speed: {tps_str} ({warmup['eval_count']} tokens in {warmup['eval_sec']:.2f}s)\n"
                    f"     Processor: {processor} | VRAM: {size_vram_mb:,.1f} MB / Total: {size_mb:,.1f} MB | Free GPU: {free_vram_mb:,} MB"
                )

                if spill_mb == 0 and size_vram_bytes > 0:
                    send_terminal_mcp(f"  ✅ [100% GPU VRAM] Model '{target_model}' fits entirely in VRAM with zero CPU offload.")
                else:
                    send_terminal_mcp(f"  🚨 [CPU OFFLOAD DETECTED] Model '{target_model}' spilled {spill_mb:,.1f} MB ({offload_pct:.1f}%) into System RAM!")
                    audit_failed = True

        finally:
            send_terminal_mcp("\n🧹 [Cleanup] Unloading test models from VRAM...")
            self._unload_models(host, models_to_test)

        send_terminal_mcp("==============================================================================")
        if not audit_failed:
            send_terminal_mcp("🎉 All tested models fit 100% in GPU VRAM with zero CPU offloading!")
            send_terminal_mcp("==============================================================================")
        else:
            send_terminal_mcp("❌ [FAILURE] One or more models offloaded layers or KV-cache to System RAM.")
            send_terminal_mcp("==============================================================================")
            raise SystemExit(1)
