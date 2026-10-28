"""QLoRA fine-tuning with Unsloth; exports a GGUF + Ollama Modelfile.

Runs on the GPU box only (not part of the app). Works on Ampere (bf16) and Volta/V100 (fp16).

    python train.py --dataset data.jsonl --base unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit \
        --out ./out --epochs 2
"""

import argparse
import sys
from pathlib import Path

MIN_EXAMPLES = 20


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="chat-format JSONL from /v1/admin/dataset")
    parser.add_argument("--base", required=True, help="HF model id (4-bit Unsloth variant)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-seq-len", type=int, default=4096)
    parser.add_argument("--quant", default="q4_k_m", help="GGUF quantization")
    args = parser.parse_args()

    lines = [ln for ln in Path(args.dataset).read_text().splitlines() if ln.strip()]
    if len(lines) < MIN_EXAMPLES:
        print(f"only {len(lines)} examples (< {MIN_EXAMPLES}); rate more answers first")
        return 2

    import torch
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_seq_len, load_in_4bit=True, dtype=None
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        lora_alpha=args.rank,
        lora_dropout=0,
        bias="none",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    dataset = load_dataset("json", data_files=args.dataset, split="train")
    dataset = dataset.map(
        lambda ex: {"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False)}
    )
    config = SFTConfig(
        output_dir=str(Path(args.out) / "checkpoints"),
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        optim="adamw_8bit",
        bf16=bf16,
        fp16=not bf16,
        logging_steps=10,
        save_strategy="no",
        report_to="none",
    )
    try:
        trainer = SFTTrainer(
            model=model, processing_class=tokenizer, train_dataset=dataset, args=config
        )
    except TypeError:  # older trl
        trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=dataset, args=config)
    trainer.train()

    out = Path(args.out)
    model.save_pretrained_gguf(str(out / "gguf"), tokenizer, quantization_method=args.quant)
    ggufs = sorted((out / "gguf").rglob("*.gguf"), key=lambda p: p.stat().st_size)
    if not ggufs:
        print("GGUF export failed")
        return 1
    (out / "Modelfile").write_text(
        f"FROM {ggufs[-1].resolve()}\nPARAMETER temperature 0.2\nPARAMETER num_ctx 8192\n"
    )
    print(f"OK: {ggufs[-1]} and {out / 'Modelfile'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
