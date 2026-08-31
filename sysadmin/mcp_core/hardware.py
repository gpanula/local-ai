"""Hardware detection and default Winter model tier resolution.

Detects available GPU VRAM (NVIDIA / Apple Silicon / Environment Override)
and dynamically resolves the best fitting Winter multi-agent models for
each role (orchestrator, architect, coder, sysadmin, security, reviewer).
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Optional

# Standard tier constants
TIER_8GB = "8gb"
TIER_16GB = "16gb"
TIER_24GB = "24gb"

DEFAULT_TIERS = (TIER_8GB, TIER_16GB, TIER_24GB)


def detect_gpu_vram_mb() -> Optional[int]:
    """Detect available GPU VRAM in megabytes.

    Checks:
    1. WINTER_VRAM_MB environment variable override.
    2. nvidia-smi query on Linux / Windows.
    3. macOS system unified memory via sysctl.
    """
    # 1. Manual environment override
    env_vram = os.environ.get("WINTER_VRAM_MB", "").strip()
    if env_vram.isdigit():
        return int(env_vram)

    # 2. NVIDIA SMI on Linux / Windows
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
            check=True,
        )
        first_line = res.stdout.strip().splitlines()[0].strip()
        if first_line.isdigit():
            return int(first_line)
    except Exception:
        pass

    # 3. macOS Unified Memory
    if platform.system() == "Darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
                check=True,
            )
            bytes_str = res.stdout.strip()
            if bytes_str.isdigit():
                # On Apple Silicon unified memory, reserve ~60-70% for GPU context
                total_mb = int(bytes_str) // (1024 * 1024)
                return int(total_mb * 0.70)
        except Exception:
            pass

    return None


def get_hardware_tier() -> str:
    """Resolve the active hardware tier: '8gb', '16gb', or '24gb'.

    Respects WINTER_TIER or LOCALAI_TIER environment variables if provided.
    Otherwise automatically categorizes based on detected GPU VRAM.
    """
    env_tier = (os.environ.get("WINTER_TIER") or os.environ.get("LOCALAI_TIER") or "").strip().lower()
    if env_tier in DEFAULT_TIERS:
        return env_tier

    vram_mb = detect_gpu_vram_mb()
    if vram_mb is None:
        # Default conservative safe fallback
        return TIER_8GB

    if vram_mb >= 20480:  # >= 20 GB (e.g. 24GB RTX 3090/4090)
        return TIER_24GB
    elif vram_mb >= 11264:  # >= 11 GB (e.g. 16GB RTX 4080 / 12GB 3060/3080)
        return TIER_16GB
    else:  # <= 8 GB
        return TIER_8GB


def get_default_model(role: str = "coder", tier: Optional[str] = None) -> str:
    """Resolve the default Winter model tag for a given agent role and hardware tier.

    Roles supported:
    - 'coder'        -> winter-coder:<tier>
    - 'reviewer'     -> winter-reviewer:<tier>
    - 'sysadmin'     -> winter-sysadmin:<tier>
    - 'architect'    -> winter-architect:<tier>
    - 'security'     -> winter-security:<tier>
    - 'orchestrator' -> winter-orchestrator:<tier>

    Examples:
    On 24GB machine: get_default_model('coder')    -> 'winter-coder:24gb'
    On 8GB machine:  get_default_model('reviewer') -> 'winter-reviewer:8gb'
    """
    active_tier = tier or get_hardware_tier()
    clean_role = role.strip().lower()
    return f"winter-{clean_role}:{active_tier}"
