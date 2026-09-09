"""Local Fine-Tuning Engine for Winter Multi-Agent Models (SFT & DPO with QLoRA)."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from mcp_core.transport import send_terminal_mcp
from mcp_core.workspace import WORKSPACE_ROOT

import shutil

DEFAULT_MODELS_DIR = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "models")
DEFAULT_DATASET_DIR = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "training")
DEFAULT_HF_CACHE_DIR = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "hf_cache")

# Pre-quantized 4-bit base models (Default - fast download ~4.5GB vs 14GB)
WINTER_BASE_MODELS_4BIT: Dict[Tuple[str, str], Tuple[str, int]] = {
    ("coder", "8gb"): ("unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit", 16384),
    ("coder", "16gb"): ("unsloth/Qwen2.5-Coder-14B-Instruct-bnb-4bit", 32768),
    ("coder", "24gb"): ("unsloth/Qwen2.5-Coder-32B-Instruct-bnb-4bit", 16384),
    ("orchestrator", "8gb"): ("unsloth/DeepSeek-R1-Distill-Qwen-8B-bnb-4bit", 16384),
    ("orchestrator", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("orchestrator", "24gb"): ("unsloth/Qwen2.5-Coder-32B-Instruct-bnb-4bit", 16384),
    ("reviewer", "8gb"): ("unsloth/Qwen2.5-7B-Instruct-bnb-4bit", 8192),
    ("reviewer", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("reviewer", "24gb"): ("mistralai/Codestral-22B-v0.1", 32768),
    ("sysadmin", "8gb"): ("unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit", 16384),
    ("sysadmin", "16gb"): ("unsloth/Qwen2.5-Coder-14B-Instruct-bnb-4bit", 32768),
    ("sysadmin", "24gb"): ("mistralai/Codestral-22B-v0.1", 32768),
    ("architect", "8gb"): ("unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit", 16384),
    ("architect", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("architect", "24gb"): ("unsloth/Qwen2.5-Coder-32B-Instruct-bnb-4bit", 16384),
    ("security", "8gb"): ("unsloth/DeepSeek-R1-Distill-Qwen-8B-bnb-4bit", 16384),
    ("security", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("security", "24gb"): ("mistralai/Codestral-22B-v0.1", 32768),
}

# Full unquantized FP16 base models (Option: --full-model)
WINTER_BASE_MODELS_FULL: Dict[Tuple[str, str], Tuple[str, int]] = {
    ("coder", "8gb"): ("Qwen/Qwen2.5-Coder-7B-Instruct", 16384),
    ("coder", "16gb"): ("Qwen/Qwen2.5-Coder-14B-Instruct", 32768),
    ("coder", "24gb"): ("Qwen/Qwen2.5-Coder-32B-Instruct", 16384),
    ("orchestrator", "8gb"): ("deepseek-ai/DeepSeek-R1-Distill-Qwen-8B", 16384),
    ("orchestrator", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("orchestrator", "24gb"): ("Qwen/Qwen2.5-Coder-32B-Instruct", 16384),
    ("reviewer", "8gb"): ("Qwen/Qwen2.5-7B-Instruct", 8192),
    ("reviewer", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("reviewer", "24gb"): ("mistralai/Codestral-22B-v0.1", 32768),
    ("sysadmin", "8gb"): ("Qwen/Qwen2.5-Coder-7B-Instruct", 16384),
    ("sysadmin", "16gb"): ("Qwen/Qwen2.5-Coder-14B-Instruct", 32768),
    ("sysadmin", "24gb"): ("mistralai/Codestral-22B-v0.1", 32768),
    ("architect", "8gb"): ("Qwen/Qwen2.5-Coder-7B-Instruct", 16384),
    ("architect", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("architect", "24gb"): ("Qwen/Qwen2.5-Coder-32B-Instruct", 16384),
    ("security", "8gb"): ("deepseek-ai/DeepSeek-R1-Distill-Qwen-8B", 16384),
    ("security", "16gb"): ("deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct", 32768),
    ("security", "24gb"): ("mistralai/Codestral-22B-v0.1", 32768),
}

# Alias for backwards compatibility
WINTER_BASE_MODELS = WINTER_BASE_MODELS_4BIT


def check_disk_space(required_gb: float, target_path: str) -> Tuple[bool, float, float]:
    """Check if target directory has at least required_gb free disk space.

    Returns: (is_sufficient, free_gb, total_gb)
    """
    check_dir = target_path
    while not os.path.exists(check_dir) and check_dir != os.path.dirname(check_dir):
        check_dir = os.path.dirname(check_dir)

    usage = shutil.disk_usage(check_dir)
    free_gb = usage.free / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    return (free_gb >= required_gb, free_gb, total_gb)


@dataclasses.dataclass
class TrainingConfig:
    role: str = "coder"
    tier: str = "8gb"
    method: str = "dpo"  # "dpo" or "sft"
    epochs: int = 3
    learning_rate: float = 5e-5
    batch_size: int = 1
    gradient_accumulation_steps: int = 4
    max_seq_length: int = 4096
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    use_4bit_base: bool = True  # Default: pre-quantized 4-bit (minimal download)
    dataset_path: Optional[str] = None
    output_dir: Optional[str] = None
    cache_dir: Optional[str] = None
    alias_active: bool = False

    @property
    def model_tag(self) -> str:
        return f"winter-{self.role}:{self.tier}-trained"

    @property
    def active_alias_tag(self) -> str:
        return f"winter-{self.role}:{self.tier}"

    @property
    def base_hf_model(self) -> str:
        key = (self.role.lower(), self.tier.lower())
        models_map = WINTER_BASE_MODELS_4BIT if self.use_4bit_base else WINTER_BASE_MODELS_FULL
        return models_map.get(key, ("unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit", 16384))[0]

    @property
    def context_window(self) -> int:
        key = (self.role.lower(), self.tier.lower())
        models_map = WINTER_BASE_MODELS_4BIT if self.use_4bit_base else WINTER_BASE_MODELS_FULL
        return models_map.get(key, ("unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit", 16384))[1]

    @property
    def estimated_download_gb(self) -> float:
        """Estimate download and working space needed for base model."""
        if self.tier == "8gb":
            return 6.0 if self.use_4bit_base else 16.0
        elif self.tier == "16gb":
            return 12.0 if self.use_4bit_base else 30.0
        else:
            return 22.0 if self.use_4bit_base else 65.0


def resolve_training_dataset(config: TrainingConfig) -> str:
    """Ensure dataset exists and return its path."""
    if config.dataset_path and os.path.exists(config.dataset_path):
        return config.dataset_path

    filename = "dpo_dataset.jsonl" if config.method == "dpo" else "sft_direct_dataset.jsonl"
    target_path = os.path.join(DEFAULT_DATASET_DIR, filename)

    if not os.path.exists(target_path):
        from mcp_core.dataset import export_datasets
        export_datasets(output_dir=DEFAULT_DATASET_DIR, formats=[config.method], include_synthetic_lessons=True)

    return target_path


# Mapping of Winter roles and tiers to local Ollama base models
WINTER_OLLAMA_BASE_MODELS: Dict[Tuple[str, str], str] = {
    ("coder", "8gb"): "qwen2.5-coder:7b",
    ("coder", "16gb"): "qwen2.5-coder:14b",
    ("coder", "24gb"): "qwen2.5-coder:32b",
    ("orchestrator", "8gb"): "deepseek-r1:8b",
    ("orchestrator", "16gb"): "deepseek-coder-v2:16b",
    ("orchestrator", "24gb"): "qwen2.5-coder:32b",
    ("reviewer", "8gb"): "qwen2.5:7b",
    ("reviewer", "16gb"): "deepseek-coder-v2:16b",
    ("reviewer", "24gb"): "codestral:22b",
    ("sysadmin", "8gb"): "qwen2.5-coder:7b",
    ("sysadmin", "16gb"): "qwen2.5-coder:14b",
    ("sysadmin", "24gb"): "codestral:22b",
    ("architect", "8gb"): "qwen2.5-coder:7b",
    ("architect", "16gb"): "deepseek-coder-v2:16b",
    ("architect", "24gb"): "qwen2.5-coder:32b",
    ("security", "8gb"): "deepseek-r1:8b",
    ("security", "16gb"): "deepseek-coder-v2:16b",
    ("security", "24gb"): "codestral:22b",
}


def export_lora_to_gguf(adapter_dir: str) -> str:
    """Convert a PEFT LoRA safetensors adapter to native GGUF format for Ollama."""
    import json
    import torch
    from safetensors.torch import load_file
    import gguf

    config_path = os.path.join(adapter_dir, "adapter_config.json")
    safetensors_path = os.path.join(adapter_dir, "adapter_model.safetensors")
    gguf_output_path = os.path.join(adapter_dir, "adapter.gguf")

    if not os.path.isfile(safetensors_path) or not os.path.isfile(config_path):
        return safetensors_path

    with open(config_path, "r", encoding="utf-8") as f:
        lora_cfg = json.load(f)

    lora_alpha = float(lora_cfg.get("lora_alpha", 32.0))
    tensors = load_file(safetensors_path)

    # Standard tensor mapping for Qwen/Llama/Mistral architectures in llama.cpp / Ollama
    name_map = {
        "self_attn.q_proj": "attn_q",
        "self_attn.k_proj": "attn_k",
        "self_attn.v_proj": "attn_v",
        "self_attn.o_proj": "attn_output",
        "mlp.gate_proj": "ffn_gate",
        "mlp.up_proj": "ffn_up",
        "mlp.down_proj": "ffn_down",
    }

    writer = gguf.GGUFWriter(gguf_output_path, "qwen2")
    writer.add_string("general.type", "adapter")
    writer.add_string("adapter.type", "lora")
    writer.add_float32("adapter.lora.alpha", lora_alpha)

    for k, v in tensors.items():
        clean_k = k
        if clean_k.startswith("base_model.model."):
            clean_k = clean_k[len("base_model.model."):]
        if clean_k.startswith("model."):
            clean_k = clean_k[len("model."):]

        parts = clean_k.split(".")
        if "layers" in parts:
            layer_idx = parts[parts.index("layers") + 1]
            layer_prefix = f"blk.{layer_idx}."
        else:
            layer_prefix = ""

        mapped_name = None
        for proj, target in name_map.items():
            if proj in clean_k:
                suffix = ".weight.lora_a" if "lora_A" in clean_k else ".weight.lora_b"
                mapped_name = f"{layer_prefix}{target}{suffix}"
                break

        if not mapped_name:
            mapped_name = clean_k

        tensor_np = v.detach().cpu().to(torch.float32).numpy()
        writer.add_tensor(mapped_name, tensor_np)

    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()

    send_terminal_mcp(f"  ✓ Exported GGUF LoRA adapter: `{gguf_output_path}`")
    return gguf_output_path


def create_trained_modelfile(config: TrainingConfig, adapter_dir: str) -> str:
    """Generate an Ollama Modelfile pointing to the base model and fine-tuned adapter."""
    ollama_base = WINTER_OLLAMA_BASE_MODELS.get((config.role.lower(), config.tier.lower()), "qwen2.5-coder:7b")

    # Export or resolve native GGUF adapter
    adapter_file = os.path.join(adapter_dir, "adapter.gguf")
    if not os.path.isfile(adapter_file):
        try:
            adapter_file = export_lora_to_gguf(adapter_dir)
        except Exception:
            adapter_file = os.path.join(adapter_dir, "adapter_model.safetensors")

    # Find template Modelfile for system prompt and parameters
    template_dir = os.path.join(WORKSPACE_ROOT, "ollama_update", "customized_models", config.tier)
    system_prompt = "You are Winter Coder, a precision code synthesis engine."

    if os.path.isdir(template_dir):
        for fname in os.listdir(template_dir):
            if f"-{config.role}-" in fname and "-trained" not in fname:
                try:
                    with open(os.path.join(template_dir, fname), "r", encoding="utf-8") as f:
                        content = f.read()
                        if 'SYSTEM """' in content:
                            system_prompt = content.split('SYSTEM """')[1].split('"""')[0]
                except Exception:
                    pass
                break

    modelfile_content = f"""# Auto-generated Modelfile for fine-tuned Winter Model: {config.model_tag}
# Created from LoRA adapter in: {adapter_dir}
FROM {ollama_base}
ADAPTER {adapter_file}

PARAMETER num_ctx {config.context_window}
PARAMETER num_predict 4096
PARAMETER temperature 0.0
PARAMETER top_p 0.95
PARAMETER repeat_penalty 1.05

SYSTEM \"\"\"{system_prompt.strip()}\"\"\"
"""
    # Write to adapter directory
    adapter_modelfile = os.path.join(adapter_dir, "Modelfile")
    with open(adapter_modelfile, "w", encoding="utf-8") as f:
        f.write(modelfile_content)

    # Also write to customized_models directory for the builder script
    if os.path.isdir(template_dir):
        tier_modelfile = os.path.join(template_dir, f"Modelfile-{config.role}-trained")
        with open(tier_modelfile, "w", encoding="utf-8") as f:
            f.write(modelfile_content)
        # Copy adapter_config.json into template directory for Ollama adapter conversion
        cfg_source = os.path.join(adapter_dir, "adapter_config.json")
        if os.path.isfile(cfg_source):
            shutil.copy2(cfg_source, os.path.join(template_dir, "adapter_config.json"))

    return adapter_modelfile


def register_model_in_ollama(modelfile_path: str, model_tag: str, alias_tag: Optional[str] = None) -> bool:
    """Create and tag model in Ollama."""
    send_terminal_mcp(f"📦 Registering trained model in Ollama: `{model_tag}`...")
    modelfile_dir = os.path.dirname(os.path.abspath(modelfile_path))
    res = subprocess.run(
        ["ollama", "create", model_tag, "-f", modelfile_path],
        cwd=modelfile_dir,
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        send_terminal_mcp(f"❌ [ERROR] Failed to register model in Ollama:\n{res.stderr}")
        return False

    if alias_tag and alias_tag != model_tag:
        send_terminal_mcp(f"🏷️  Aliasing `{model_tag}` -> `{alias_tag}`...")
        cp_res = subprocess.run(
            ["ollama", "cp", model_tag, alias_tag],
            capture_output=True, text=True,
        )
        if cp_res.returncode != 0:
            send_terminal_mcp(f"⚠️ [WARNING] Failed to set alias:\n{cp_res.stderr}")
            return False

    send_terminal_mcp(f"✅ Successfully registered `{model_tag}` in Ollama!")
    return True
