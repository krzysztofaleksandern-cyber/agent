# TASKS.md

Status: `[ ]` todo · `[~]` in progress · `[x]` done. Each phase ends with: tests green,
ruff clean, docs updated, commit, summary, STOP.

## Phase 1 – Skeleton ✅
- [x] `pyproject.toml` (deps, ruff, pytest config), `.gitignore`, `.env.example`
- [x] `app/config.py` – `Settings` (env prefix-free, `.env` support, `SecretStr` for keys)
- [x] `app/logging.py` – logging setup, `redact()` helper for secrets / message previews
- [x] `app/main.py` – `create_app()`, `GET /health` (status, version)
- [x] `Dockerfile` (python:3.12-slim, non-root), `docker-compose.yml`
- [x] `.pre-commit-config.yaml` (ruff, ruff-format)
- [x] tests: config loading, redaction, /health

## Phase 2 – WhatsApp gateway (Cloud API)
- [ ] `GET /webhook` – hub.mode/verify_token/challenge handshake
- [ ] `POST /webhook` – HMAC-SHA256 check of `X-Hub-Signature-256` against raw body (app secret)
- [ ] payload parsing (text, audio) into an internal `IncomingMessage` model
- [ ] owner allowlist (ignore other numbers silently)
- [ ] dedup by message id (TTL cache; persisted in Phase 3)
- [ ] `WhatsAppSender.send_text()` with splitting of long messages (4096-char limit, split on paragraph/line)
- [ ] tests with signed fixture payloads and `httpx.MockTransport`

## Phase 3 – Task queue & persistence
- [ ] SQLite schema: tasks (id, source_msg_id, text, status, attempts, result, error, timestamps), processed_messages
- [ ] statuses: queued → running → done | failed | cancelled
- [ ] asyncio worker (single consumer), retry with backoff, max attempts
- [ ] cancellation: "stop" message cancels the running task (`asyncio.Task.cancel`) + queued ones
- [ ] tests: lifecycle, retry, cancel, restart recovery (running → queued)

## Phase 4 – STT
- [ ] `Transcriber` protocol: `transcribe(path) -> Transcript(text, language)`
- [ ] media download from Cloud API (`/media/{id}` → URL → file)
- [ ] `WhisperTranscriber` (faster-whisper, CPU, int8, lazy model load, languages pl/de/en)
- [ ] voice note → transcript → task; tests with a fake transcriber (real model test marked/skipped)

## Phase 5 – LLM client
- [ ] `LLMClient` protocol: `chat(messages, tools=None) -> LLMResponse` (text + tool_calls + usage)
- [ ] `OpenAICompatClient` (httpx, `/v1/chat/completions`, timeouts, retry on 429/5xx, typed errors)
- [ ] `MockLLM` (scripted responses incl. tool calls)
- [ ] tests via `httpx.MockTransport`

## Phase 6 – Sandbox
- [ ] `Dockerfile.sandbox` (python:3.12-slim + git, pytest, ruff)
- [ ] `SandboxRunner` protocol + `DockerSandbox`: `docker run --rm --network none --cpus --memory --pids-limit --read-only` + mounted /workspace, timeout (kill), output truncation
- [ ] tests: command construction, truncation, timeout (fake process); real-docker test marked

## Phase 7 – Agent loop
- [ ] tools: `shell`, `read_file`, `write_file`, `git`, `http_get` (domain allowlist)
- [ ] path jail: resolve and reject anything outside /workspace (symlinks, `..`)
- [ ] loop: LLM ↔ tools, max steps, tool error handling, final summary sent to owner
- [ ] tests with MockLLM scripts

## Phase 8 – Approval gate
- [ ] risk classifier (git push, deploy, rm/delete, spending, http to non-allowlisted)
- [ ] `ApprovalGate.request(action) -> bool` – sends WhatsApp prompt, waits for TAK/NIE, timeout = deny
- [ ] incoming TAK/NIE routed to pending approval instead of a new task
- [ ] tests: approve, deny, timeout

## Phase 9 – Free-API router
- [ ] `providers.yaml` (Groq, Gemini via OpenAI-compat endpoint, OpenRouter, Mistral…; keys from env)
- [ ] `RouterLLM` implementing `LLMClient`: ordered fallback, per-provider rate limit (token bucket), request counter (SQLite), response cache (hash of request, TTL)
- [ ] tests: fallback on error/429, rate-limit skip, cache hit

## Phase 10 – Memory & "learning"
- [ ] `Embedder` protocol (+ simple hashing embedder for tests; OpenAI-compat embeddings impl)
- [ ] SQLite store of Q/A pairs with quality score + vectors (numpy-free cosine in Python)
- [ ] RAG: search memory before external API call; inject top-k as context
- [ ] owner feedback → quality score; `export_jsonl()` for fine-tuning (chat format, min score filter)
- [ ] tests

## Phase 11 – Deployment
- [ ] `deploy/docker-compose.yml` (app + vLLM service, volumes, healthchecks)
- [ ] `deploy/start.sh`, `deploy/agent.service` (systemd)
- [ ] README: setup steps (Meta app, webhook, env, vLLM), security checklist

## Phase 12 – (optional, only on request) TTS voice replies
