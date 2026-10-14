"""Unit tests for Winter local model fine-tuning and trainer components."""

import os
import tempfile
import pytest

from mcp_core.trainer import (
    TrainingConfig,
    WINTER_BASE_MODELS,
    resolve_training_dataset,
    create_trained_modelfile,
)
from mcp_core.dataset import (
    synthesize_lesson_contrastive_pairs,
    export_datasets,
)


def test_winter_base_models_mapping():
    """Verify all 6 Winter roles across all 3 tiers map to valid base models."""
    roles = ["coder", "orchestrator", "reviewer", "sysadmin", "architect", "security"]
    tiers = ["8gb", "16gb", "24gb"]

    for role in roles:
        for tier in tiers:
            assert (role, tier) in WINTER_BASE_MODELS
            repo_id, ctx = WINTER_BASE_MODELS[(role, tier)]
            assert isinstance(repo_id, str) and len(repo_id) > 0
            assert isinstance(ctx, int) and ctx >= 4096


def test_training_config_properties():
    """Verify TrainingConfig tags and model resolutions."""
    config_coder_8gb = TrainingConfig(role="coder", tier="8gb", method="dpo")
    assert config_coder_8gb.model_tag == "winter-coder:8gb-trained"
    assert config_coder_8gb.active_alias_tag == "winter-coder:8gb"
    assert config_coder_8gb.base_hf_model == "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
    assert config_coder_8gb.context_window == 16384

    # Full FP16 model option
    config_coder_full = TrainingConfig(role="coder", tier="8gb", use_4bit_base=False)
    assert config_coder_full.base_hf_model == "Qwen/Qwen2.5-Coder-7B-Instruct"

    config_orch_16gb = TrainingConfig(role="orchestrator", tier="16gb", method="sft")
    assert config_orch_16gb.model_tag == "winter-orchestrator:16gb-trained"
    assert config_orch_16gb.base_hf_model == "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct"
    assert config_orch_16gb.context_window == 32768

    config_rev_24gb = TrainingConfig(role="reviewer", tier="24gb", method="dpo")
    assert config_rev_24gb.model_tag == "winter-reviewer:24gb-trained"
    assert config_rev_24gb.base_hf_model == "mistralai/Codestral-22B-v0.1"


def test_check_disk_space():
    """Verify disk space checking utility."""
    from mcp_core.trainer import check_disk_space
    has_space, free_gb, total_gb = check_disk_space(1.0, "/tmp")
    assert isinstance(has_space, bool)
    assert free_gb > 0
    assert total_gb > 0


def test_synthesize_lesson_contrastive_pairs():
    """Verify synthetic lesson contrastive pairs are generated properly."""
    pairs = synthesize_lesson_contrastive_pairs()
    assert len(pairs) >= 6

    for p in pairs:
        assert "id" in p
        assert "prompt" in p and len(p["prompt"]) > 0
        assert "rejected" in p and len(p["rejected"]) > 0
        assert "chosen" in p and len(p["chosen"]) > 0
        assert p["rejected"] != p["chosen"]
        assert "explanation" in p


def test_export_datasets_with_synthetic_lessons():
    """Verify export_datasets combines trajectories with synthetic lessons."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        counts = export_datasets(
            output_dir=tmp_dir,
            formats=["dpo", "sft_direct", "sft_multiturn"],
            include_synthetic_lessons=True,
        )
        assert counts["dpo"] >= 6
        assert counts["sft_direct"] >= 6
        assert counts["sft_multiturn"] >= 6

        dpo_file = os.path.join(tmp_dir, "dpo_dataset.jsonl")
        assert os.path.isfile(dpo_file)
        with open(dpo_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            assert len(lines) == counts["dpo"]


def test_create_trained_modelfile():
    """Verify Modelfile generation for trained adapter."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = TrainingConfig(role="coder", tier="8gb")
        modelfile_path = create_trained_modelfile(config, tmp_dir)

        assert os.path.isfile(modelfile_path)
        with open(modelfile_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "ADAPTER" in content
            assert tmp_dir in content
            assert "winter-coder:8gb-trained" in content
            assert "num_ctx 16384" in content
            assert "SYSTEM" in content
