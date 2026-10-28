# TASKS.md

Status: `[ ]` todo · `[~]` in progress · `[x]` done. Each phase ends with: tests green,
ruff clean, docs updated, commit, summary, STOP.

## Phase 1 – Skeleton ✅
- [x] `pyproject.toml` (deps, ruff, pytest config), `.gitignore`, `.env.example`
- [x] `app/config.py` – `Settings` (`.env` support, `SecretStr` for keys)
- [x] `app/logging.py` – logging setup, `redact()` helper for secrets / message previews
- [x] `app/main.py` – `create_app()`, `GET /health` (status, version)
- [x] `Dockerfile` (python:3.12-slim, non-root), `docker-compose.yml`
- [x] `.pre-commit-config.yaml` (ruff, ruff-format)
- [x] tests: config loading, redaction, /health

## Phase 2 – Model layer (local models) ✅
- [x] `LLMClient` protocol + types (`ChatMessage`, `ToolCall`, `LLMResponse`, `Usage`, typed errors)
- [x] `OpenAICompatClient` (httpx → Ollama/vLLM `/v1/chat/completions`, timeouts, retry on 429/5xx/connect errors, tool calls)
- [x] `MockLLM` (scripted replies incl. tool calls, records requests)
- [x] `config/models.yaml` + `ModelRegistry`: backends, model aliases, fallback chains
- [x] `UsageMeter` (requests, tokens, errors, latency per alias; in-memory, persisted in Phase 5)
- [x] `OllamaAdmin` (list / pull models via native Ollama API)
- [x] remove WhatsApp settings; add `MODELS_CONFIG`, `OLLAMA_URL`
- [x] tests via `httpx.MockTransport`

## Phase 3 – Public API ✅
- [x] SQLite API-key store (hashed keys, labels), CLI to create/revoke keys
- [x] `POST /v1/chat/completions` (OpenAI schema, `model` = agent or model alias), streaming (SSE; single delta for now — token streaming later)
- [x] `GET /v1/models` (agents + aliases)
- [x] tests
- [x] `GET /v1/admin/usage` (admin key)

## Phase 4 – Agent profiles ✅
- [x] `config/agents.yaml`: name, description, system prompt, model alias, tools, temperature, max_steps
- [x] starter agents: `orchestrator`, `codex`, `writer`, `auditor`
- [x] admin endpoints: list/get/update agents (admin key)
- [x] tests

## Phase 5 – Tasks & persistence ✅
- [x] SQLite tasks (queued → running → done | failed | cancelled), attempts, result, error
- [x] asyncio worker, retry with backoff, cancel, restart recovery
- [x] `POST /v1/tasks`, `GET /v1/tasks/{id}`, `POST /v1/tasks/{id}/cancel`, webhook on completion (HMAC-signed)
- [x] persist usage counters
- [x] tests

## Phase 6 – Tools & sandbox ✅
- [x] `Dockerfile.sandbox` (python:3.12-slim + git, ssh, pytest, ruff, node)
- [x] `DockerSandbox`: `--network none`, CPU/RAM/PID limits, timeout, output truncation, per-task /workspace volume
- [x] tools: `shell`, `read_file`, `write_file`, `list_dir`, `git`, `http_get` (domain allowlist); path jail
- [x] tests (fake runner; real Docker marked)
- [x] `LocalRunner` (no isolation, dev only) via `SANDBOX_BACKEND=local`

## Phase 7 – Agent loop & orchestration ✅
- [x] tool-calling loop with step limit, tool error feedback, final summary
- [x] `delegate(agent, task)` tool for the orchestrator (depth limit)
- [x] fallback for models without native tool calling (JSON tool protocol in prompt)
- [x] tests with MockLLM scripts

## Phase 8 – Approvals ✅
- [x] risk classifier (git push, deploy, rm/delete, network writes)
- [x] pending approvals: `GET /v1/approvals`, `POST /v1/approvals/{id}` (yes/no), webhook notification; timeout = deny
- [x] tests
- [x] answers accept TAK/NIE/yes/no/ja/nein; `APPROVAL_MODE=off` disables the gate

## Phase 9 – Memory ✅
- [x] SQLite: conversations, messages, ratings (`POST /v1/feedback`), lessons
- [x] `Embedder` protocol + Ollama embeddings (`nomic-embed-text`), pure-Python cosine search
- [x] RAG: relevant history + lessons injected into the agent context
- [x] self-reflection: after a task the agent writes a short lesson
- [x] tests
- [x] owner rules (`POST /v1/admin/lessons`) always injected; low rating + comment → lesson
- [x] `HashEmbedder` fallback (no model needed)

## Phase 10 – Learning (fine-tuning) ✅
- [x] dataset builder: rated conversations → JSONL (chat format, min score, dedup)
- [x] `training/` image + script: QLoRA via Unsloth (fp16 fallback for Volta), export GGUF/adapter
- [x] register new version in Ollama (`Modelfile` with ADAPTER), version table
- [x] eval suite (fixed prompts + checks) → promote or rollback
- [x] tests (builder, versioning, eval logic); `train.py` not run here (needs GPU)
- [x] `training/run_cycle.sh`: dataset → train → `ollama create` → evaluate/promote

## Phase 11 – Deployment ✅
- [x] `deploy/vps/docker-compose.yml` (app + Caddy HTTPS, Docker socket for sandboxes, data at identical host/container path)
- [x] `deploy/vps/start.sh`, `devagent.service` (systemd), `backup.sh` (SQLite backup)
- [x] `deploy/gpu/onstart.sh` for Vast.ai (Tailscale userspace, Ollama on localhost, model pulls)
- [x] Dockerfile ships the Docker CLI; root compose kept for local dev
- [x] README: step-by-step setup, model choice per GPU (V100S 32 GB / RTX 3090 Ti 24 GB), API table, security checklist

## Phase 12 – (optional, only on request) TTS voice replies
- [ ] skipped: owner already has TTS in their own apps
