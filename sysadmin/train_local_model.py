#!/usr/bin/env python3
"""Fine-tune Winter Multi-Agent Models using QLoRA (SFT & DPO) on local GPU."""

import argparse
import os
import sys
import time

# Disable experimental Hugging Face Xet transfer to prevent file reconstruction errors
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

# Ensure sysadmin directory is on path
REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "sysadmin"))

from mcp_core.transport import send_terminal_mcp
from mcp_core.trainer import (
    TrainingConfig,
    resolve_training_dataset,
    create_trained_modelfile,
    register_model_in_ollama,
    check_disk_space,
    DEFAULT_MODELS_DIR,
    DEFAULT_HF_CACHE_DIR,
)


def run_qlora_training(config: TrainingConfig) -> str:
    """Execute 4-bit QLoRA fine-tuning loop using PyTorch, PEFT, and TRL."""
    # Ensure cache directory on fast, high-capacity drive
    cache_dir = config.cache_dir or DEFAULT_HF_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["HF_HOME"] = cache_dir

    # 1. Assert sufficient disk space
    req_gb = config.estimated_download_gb
    has_space, free_gb, total_gb = check_disk_space(req_gb, cache_dir)

    send_terminal_mcp("==============================================================================")
    send_terminal_mcp(f"🔥 Starting Winter Local Model Fine-Tuning: {config.model_tag}")
    send_terminal_mcp("==============================================================================")
    send_terminal_mcp(f"  Target Role:   {config.role.upper()} ({config.tier.upper()} Tier)")
    send_terminal_mcp(f"  Base Model:    {config.base_hf_model} ({'Pre-quantized 4-bit' if config.use_4bit_base else 'Full FP16'})")
    send_terminal_mcp(f"  HF Cache Dir:  {cache_dir} ({free_gb:,.1f} GB free / {total_gb:,.1f} GB total)")
    send_terminal_mcp(f"  Method:        {config.method.upper()}")

    if not has_space:
        send_terminal_mcp(f"❌ [DISK SPACE ERROR] Insufficient disk space in `{cache_dir}`!")
        send_terminal_mcp(f"   Required: ~{req_gb:.1f} GB | Available: {free_gb:.1f} GB.")
        sys.exit(1)

    dataset_file = resolve_training_dataset(config)
    adapter_out_dir = config.output_dir or os.path.join(DEFAULT_MODELS_DIR, f"winter-{config.role}-{config.tier}-adapter")
    os.makedirs(adapter_out_dir, exist_ok=True)

    send_terminal_mcp(f"  Dataset:       {dataset_file}")
    send_terminal_mcp(f"  Epochs:        {config.epochs} | Learning Rate: {config.learning_rate}")
    send_terminal_mcp(f"  Adapter Out:   {adapter_out_dir}")
    send_terminal_mcp("------------------------------------------------------------------------------")

    # 2. Verify CUDA
    import torch
    if not torch.cuda.is_available():
        send_terminal_mcp("❌ [ERROR] CUDA is not available. Local GPU training requires an NVIDIA GPU.")
        sys.exit(1)

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    send_terminal_mcp(f"  GPU Device:    {gpu_name} ({vram_gb:.1f} GB VRAM)")
    send_terminal_mcp("==============================================================================")

    # 3. Configure 4-bit Quantization
    send_terminal_mcp("\n📦 Loading Base Model & Tokenizer with 4-bit NormalFloat quantization...")
    from datasets import load_dataset
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(
        config.base_hf_model,
        cache_dir=cache_dir,
        trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        config.base_hf_model,
        quantization_config=bnb_config,
        cache_dir=cache_dir,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    # 3. LoRA Adapter Config
    peft_config = LoraConfig(
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
        task_type="CAUSAL_LM",
    )

    # 4. Load Dataset
    raw_dataset = load_dataset("json", data_files=dataset_file)["train"]
    send_terminal_mcp(f"  📚 Training Samples:    {len(raw_dataset):,} samples loaded")

    # 5. Execute Trainer
    start_time = time.perf_counter()

    if config.method == "dpo":
        from trl import DPOConfig, DPOTrainer
        send_terminal_mcp("\n🚀 Running Direct Preference Optimization (DPO)...")
        dpo_args = DPOConfig(
            output_dir=adapter_out_dir,
            num_train_epochs=config.epochs,
            per_device_train_batch_size=config.batch_size,
            gradient_accumulation_steps=config.gradient_accumulation_steps,
            learning_rate=config.learning_rate,
            logging_steps=1,
            save_strategy="epoch",
            bf16=torch.cuda.is_bf16_supported(),
            fp16=not torch.cuda.is_bf16_supported(),
            optim="paged_adamw_8bit",
            report_to="none",
            max_length=config.max_seq_length,
        )
        trainer = DPOTrainer(
            model=model,
            args=dpo_args,
            peft_config=peft_config,
            train_dataset=raw_dataset,
            processing_class=tokenizer,
        )
    else:
        from trl import SFTConfig, SFTTrainer
        send_terminal_mcp("\n🚀 Running Supervised Fine-Tuning (SFT)...")
        sft_args = SFTConfig(
            output_dir=adapter_out_dir,
            num_train_epochs=config.epochs,
            per_device_train_batch_size=config.batch_size,
            gradient_accumulation_steps=config.gradient_accumulation_steps,
            learning_rate=config.learning_rate,
            logging_steps=1,
            save_strategy="epoch",
            bf16=torch.cuda.is_bf16_supported(),
            fp16=not torch.cuda.is_bf16_supported(),
            optim="paged_adamw_8bit",
            report_to="none",
            max_seq_length=config.max_seq_length,
            dataset_text_field="messages",
        )
        trainer = SFTTrainer(
            model=model,
            args=sft_args,
            peft_config=peft_config,
            train_dataset=raw_dataset,
            processing_class=tokenizer,
        )

    trainer.train()
    elapsed_sec = time.perf_counter() - start_time

    # 7. Save Adapter
    send_terminal_mcp(f"\n💾 Saving fine-tuned LoRA adapter to `{adapter_out_dir}`...")
    trainer.save_model(adapter_out_dir)
    tokenizer.save_pretrained(adapter_out_dir)

    send_terminal_mcp(f"🎉 Training complete in {elapsed_sec:.1f}s ({elapsed_sec / 60:.2f} min)!")

    # 8. Package & Register in Ollama
    modelfile = create_trained_modelfile(config, adapter_out_dir)
    alias = config.active_alias_tag if config.alias_active else None
    register_model_in_ollama(modelfile, config.model_tag, alias_tag=alias)

    return adapter_out_dir


def main():
    parser = argparse.ArgumentParser(description="Local Model Fine-Tuning for Winter")
    parser.add_argument("--role", choices=["coder", "orchestrator", "reviewer", "sysadmin", "architect", "security"], default="coder")
    parser.add_argument("--tier", choices=["8gb", "16gb", "24gb"], default="8gb")
    parser.add_argument("--method", choices=["dpo", "sft"], default="dpo")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--max-seq-len", type=int, default=4096)
    parser.add_argument("--dataset-path", default=None, help="Path to input JSONL dataset")
    parser.add_argument("--full-model", action="store_true", help="Download and train on full FP16 base model instead of pre-quantized 4-bit")
    parser.add_argument("--cache-dir", default=None, help="Directory to store downloaded Hugging Face weights")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--alias-active", action="store_true")

    args = parser.parse_args()

    config = TrainingConfig(
        role=args.role,
        tier=args.tier,
        method=args.method,
        epochs=args.epochs,
        learning_rate=args.lr,
        batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        max_seq_length=args.max_seq_len,
        use_4bit_base=not args.full_model,
        dataset_path=args.dataset_path,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        alias_active=args.alias_active,
    )

    run_qlora_training(config)


if __name__ == "__main__":
    main()
