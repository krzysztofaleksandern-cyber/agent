# Learning cycle (fine-tuning)

The app collects every agent answer. When you rate answers (`POST /v1/feedback`, 1-5),
the good ones (>= 4) become training data. On the GPU box:

```bash
pip install -r training/requirements.txt
export API_URL=http://<vps-tailscale-ip>:8080 ADMIN_API_KEY=...
ALIAS=coder AGENT=codex BASE_HF=unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit ./training/run_cycle.sh
```

What happens:
1. `GET /v1/admin/dataset` exports rated conversations as chat JSONL (deduplicated).
2. `train.py` runs QLoRA (Unsloth; bf16 on RTX 30xx/40xx, fp16 on V100) and exports GGUF.
3. `ollama create devagent-coder:<date>` registers the new model in Ollama.
4. `POST /v1/admin/candidates` runs `config/eval.yaml` against the candidate **and** the
   current model. The candidate replaces the alias only if it scores at least as well
   (and >= `LEARNING_MIN_SCORE`). Otherwise it is rejected and nothing changes.
5. Undo any time: `POST /v1/admin/versions/coder/rollback`.

Tips
- Pick `BASE_HF` matching the alias size (alias `coder` = 14B? use the 14B Unsloth model;
  14B QLoRA fits in 24 GB, 32B needs the 32 GB V100 with short sequences).
- At least 20 rated examples are required; a few hundred give noticeable results.
- Extend `config/eval.yaml` with your own real tasks - it is your safety net.
- Schedule weekly with cron on the GPU box once enough data accumulates.
