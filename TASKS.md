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

## Phase 5 – Tasks & persistence
- [ ] SQLite tasks (queued → running → done | failed | cancelled), attempts, result, error
- [ ] asyncio worker, retry with backoff, cancel, restart recovery
- [ ] `POST /v1/tasks`, `GET /v1/tasks/{id}`, `POST /v1/tasks/{id}/cancel`, webhook on completion (HMAC-signed)
- [ ] persist usage counters
- [ ] tests

## Phase 6 – Tools & sandbox
- [ ] `Dockerfile.sandbox` (python:3.12-slim + git, pytest, ruff, node)
- [ ] `DockerSandbox`: `--network none`, CPU/RAM/PID limits, timeout, output truncation, per-task /workspace volume
- [ ] tools: `shell`, `read_file`, `write_file`, `list_dir`, `git`, `http_get` (domain allowlist); path jail
- [ ] tests (fake runner; real Docker marked)

## Phase 7 – Agent loop & orchestration
- [ ] tool-calling loop with step limit, tool error feedback, final summary
- [ ] `delegate(agent, task)` tool for the orchestrator (depth limit)
- [ ] fallback for models without native tool calling (JSON tool protocol in prompt)
- [ ] tests with MockLLM scripts

## Phase 8 – Approvals
- [ ] risk classifier (git push, deploy, rm/delete, network writes)
- [ ] pending approvals: `GET /v1/approvals`, `POST /v1/approvals/{id}` (yes/no), webhook notification; timeout = deny
- [ ] tests

## Phase 9 – Memory
- [ ] SQLite: conversations, messages, ratings (`POST /v1/feedback`), lessons
- [ ] `Embedder` protocol + Ollama embeddings (`nomic-embed-text`), pure-Python cosine search
- [ ] RAG: relevant history + lessons injected into the agent context
- [ ] self-reflection: after a task the agent writes a short lesson
- [ ] tests

## Phase 10 – Learning (fine-tuning)
- [ ] dataset builder: rated conversations → JSONL (chat format, min score, dedup)
- [ ] `training/` image + script: QLoRA via Unsloth (fp16 fallback for Volta), export GGUF/adapter
- [ ] register new version in Ollama (`Modelfile` with ADAPTER), version table
- [ ] eval suite (fixed prompts + checks) → promote or rollback
- [ ] tests (builder, versioning, eval logic; training itself marked)

## Phase 11 – Deployment
- [ ] `deploy/vps/docker-compose.yml` (app + sandbox image), `deploy/gpu/` (Ollama + training, Vast.ai onstart script)
- [ ] WireGuard/Tailscale tunnel guide, systemd unit, backups of data volume
- [ ] README: step-by-step setup, model choice per GPU (V100S 32 GB / RTX 3090 Ti 24 GB), security checklist
