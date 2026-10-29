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

## Phase 12 – Gemini provider with key rotation ✅
- [x] `RotatingKeyClient`: round-robins over several API keys, cooldown on 429/5xx
- [x] backend `keys_env` (comma-separated keys) wired into `ModelRegistry`
- [x] `config/models.yaml`: gemini backend + `gemini-pro`/`gemini-flash` aliases
- [x] `GEMINI_API_KEYS` in `.env.example`; tests for rotation and exhaustion

## Part 2 – New agents (in progress)
- [x] Phase 12: Gemini provider with 5-key rotation
- [x] Phase 13: `operator` agent + host worker (control the owner's own computer)
- [x] Phase 14: phone PWA with one-time-password login (Chrome, no install)

(TTS skipped: owner already has a voice agent of their own.)

### Phase 13 details – operator agent & host worker ✅
- [x] `OperatorHub`: long-poll command channel VPS <-> host worker, dispatch + result + online status
- [x] Operator tools (screenshot, mouse_move/click/scroll, type_text, key_press, os_run/shell/read/write/list) routed to the worker
- [x] `/v1/operator/poll` + `/v1/operator/result` (worker token), `/v1/operator/status` (admin)
- [x] `config/agents.yaml`: `operator` agent (Windows); risky os_* actions gated by approvals
- [x] `worker/operator_worker.py` (Windows, pyautogui), requirements, README
- [x] tests for hub, tools, risk classification, worker channel

### Phase 14 details – phone console (PWA) ✅
- [x] `ConsoleManager` (SQLite): single-use OTP + short-lived session tokens (hashed), shared with the CLI
- [x] `python -m app.cli console-otp` prints a one-time login code
- [x] `/console/` PWA (installable, dark, mobile): OTP login, send commands to the operator agent, live worker status, TAK/NIE approvals
- [x] session-scoped API: command/status/approvals (not an admin key); logout
- [x] tests for OTP lifecycle, CLI, and the full PWA flow

### Phase 15 – Jarvis, office agents, autostart & docs ✅
- [x] Windows worker autostart (Task Scheduler via install_autostart.ps1) + worker/.env loading
- [x] `jarvis` super-assistant delegating to all agents (operator/secretary/codex/writer/auditor/researcher)
- [x] `secretary` (office admin via operator) and `researcher` (web + summaries) agents
- [x] ASSEMBLY.md (full end-to-end setup incl. VoiceStudio voice loop), ROADMAP.md (path to 95%-office)
- [x] tests for the new agent profiles

### Phase 16 – Email connector ✅
- [x] `ImapSmtpMailbox` (stdlib IMAP/SMTP) behind a `Mailbox` interface; `EmailConfig` from .env
- [x] tools email_list / email_read / email_send (send gated by approval)
- [x] ToolContext.services registry; AgentRunner passes connectors to tools
- [x] secretary uses the inbox directly; tests with a fake mailbox

### Phase 17 – Calendar ✅
- [x] `CalendarStore` (SQLite) with validation and .ics export (import to Outlook/Google)
- [x] tools calendar_list / calendar_create / calendar_delete (delete gated by approval)
- [x] secretary and jarvis can manage the calendar; tests included

### Phase 18 – Audit log ✅
- [x] `AuditLog` (SQLite): every tool action recorded (agent, client, tool, args, ok, note)
- [x] agent loop records each tool call (incl. denied/ failed)
- [x] GET /v1/admin/audit (admin) and /console/api/activity (phone); tests included

### Phase 19 – Scheduler (recurring jobs) ✅
- [x] `JobStore` (SQLite) + `compute_next` for every_minutes / daily HH:MM / weekly D:HH:MM (UTC)
- [x] `SchedulerLoop` fires due jobs into the task queue for the chosen agent
- [x] admin API: list/create/toggle/delete jobs; tests for schedules and firing

### Phase 20 – Company knowledge base (RAG) ✅
- [x] knowledge table in MemoryStore; chunking + embeddings; cosine search
- [x] MemoryService.ingest; relevant chunks injected into every agent's context
- [x] admin API: add / list / delete knowledge documents; tests included

### Phase 21 – Operator vision ✅
- [x] worker screenshot returns a (downscaled) image; execute() passes image_b64 through the hub
- [x] screenshot tool attaches the image to ctx.images; agent loop feeds it to the model as image_url
- [x] operator agent uses a vision model alias (operator-vision, e.g. llama3.2-vision); test included

### Phase 22 – CRM + lead capture ✅
- [x] `CrmStore` (SQLite): contacts (email de-dupe) and deals with stages; lead capture
- [x] tools crm_add_contact / crm_find_contact / crm_add_deal / crm_list_deals / crm_set_stage
- [x] POST /v1/leads for website forms (client key); sales + support agents; tests included

### Phase 23 – Safety: master pause (kill switch) ✅
- [x] `ControlState` global pause; agent loop takes no tool actions while paused
- [x] POST /v1/admin/pause (admin) and /console/api/pause (phone), big STOP button in the PWA
- [x] tests: paused runner performs no actions, resume restores action

### Phase 24 – Document generation ✅
- [x] dependency-free .docx (zipfile + OOXML) and .html from light markdown (headings, bullets, bold)
- [x] make_document tool (path extension picks format); writer + secretary can produce documents
- [x] tests validate the docx is a valid zip with headings and bold runs
