"""Unit tests for hardware tier detection and Winter model resolver."""

import os
import sys
import unittest
from unittest.mock import patch

# Ensure sysadmin directory is in sys.path
SYSADMIN_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
if SYSADMIN_DIR not in sys.path:
    sys.path.insert(0, SYSADMIN_DIR)

from mcp_core.hardware import (
    TIER_8GB,
    TIER_16GB,
    TIER_24GB,
    detect_gpu_vram_mb,
    get_default_model,
    get_hardware_tier,
)


class TestHardwareTier(unittest.TestCase):

    def test_get_default_model_explicit_tier(self):
        """Verify role model resolution with explicit tier parameter."""
        self.assertEqual(get_default_model("coder", tier=TIER_8GB), "winter-coder:8gb")
        self.assertEqual(get_default_model("reviewer", tier=TIER_8GB), "winter-reviewer:8gb")
        self.assertEqual(get_default_model("sysadmin", tier=TIER_16GB), "winter-sysadmin:16gb")
        self.assertEqual(get_default_model("architect", tier=TIER_24GB), "winter-architect:24gb")
        self.assertEqual(get_default_model("security", tier=TIER_24GB), "winter-security:24gb")
        self.assertEqual(get_default_model("orchestrator", tier=TIER_16GB), "winter-orchestrator:16gb")

    def test_get_hardware_tier_env_override(self):
        """Verify WINTER_TIER environment variable overrides detection."""
        with patch.dict(os.environ, {"WINTER_TIER": "8gb"}):
            self.assertEqual(get_hardware_tier(), "8gb")
            self.assertEqual(get_default_model("coder"), "winter-coder:8gb")

        with patch.dict(os.environ, {"WINTER_TIER": "16gb"}):
            self.assertEqual(get_hardware_tier(), "16gb")
            self.assertEqual(get_default_model("sysadmin"), "winter-sysadmin:16gb")

        with patch.dict(os.environ, {"WINTER_TIER": "24gb"}):
            self.assertEqual(get_hardware_tier(), "24gb")
            self.assertEqual(get_default_model("reviewer"), "winter-reviewer:24gb")

    def test_get_hardware_tier_vram_thresholds(self):
        """Verify VRAM threshold categorization."""
        with patch.dict(os.environ, {}, clear=True):
            # 24GB tier (>= 20GB)
            with patch("mcp_core.hardware.detect_gpu_vram_mb", return_value=24576):
                self.assertEqual(get_hardware_tier(), TIER_24GB)

            # 16GB tier (11GB - 20GB)
            with patch("mcp_core.hardware.detect_gpu_vram_mb", return_value=16384):
                self.assertEqual(get_hardware_tier(), TIER_16GB)

            with patch("mcp_core.hardware.detect_gpu_vram_mb", return_value=12288):
                self.assertEqual(get_hardware_tier(), TIER_16GB)

            # 8GB tier (<= 8GB)
            with patch("mcp_core.hardware.detect_gpu_vram_mb", return_value=8192):
                self.assertEqual(get_hardware_tier(), TIER_8GB)

            with patch("mcp_core.hardware.detect_gpu_vram_mb", return_value=6144):
                self.assertEqual(get_hardware_tier(), TIER_8GB)

            # Fallback when detection returns None
            with patch("mcp_core.hardware.detect_gpu_vram_mb", return_value=None):
                self.assertEqual(get_hardware_tier(), TIER_8GB)

    def test_detect_gpu_vram_env_override(self):
        """Verify WINTER_VRAM_MB environment variable override."""
        with patch.dict(os.environ, {"WINTER_VRAM_MB": "8192"}):
            self.assertEqual(detect_gpu_vram_mb(), 8192)


if __name__ == "__main__":
    unittest.main()
