# TASKS.md

Status: `[ ]` todo, `[x]` done. Each phase ends with: tests green, ruff clean,
docs updated, commit, stop for "dalej".

## Phase 1 – Skeleton
- [ ] `pyproject.toml` (deps, extras `dev`/`stt`, ruff + pytest config), `.gitignore`
- [ ] `config.py`: `Settings` (pydantic-settings, `.env`), `.env.example`
- [ ] `logging.py`: JSON formatter, `redact()` for secrets, `preview()` for message text
- [ ] `main.py`: app factory, lifespan, `GET /health`
- [ ] `Dockerfile` (python:3.12-slim, non-root), `docker-compose.yml`
- [ ] `.pre-commit-config.yaml` (ruff), tests for config/logging/health

## Phase 2 – WhatsApp gateway (Cloud API)
- [ ] `GET /webhook` verification (hub.mode / verify_token / challenge)
- [ ] `POST /webhook`: X-Hub-Signature-256 check (HMAC, constant-time), 403 on mismatch
- [ ] Owner whitelist; ignore others silently (log redacted number)
- [ ] Dedup by message id (TTL cache, later persisted in Phase 3)
- [ ] Parse text / audio / status events into internal `IncomingMessage`
- [ ] `WhatsAppSender`: send text, split long messages (~4000 chars, on line/word boundaries)
- [ ] Tests with signed fixture payloads, respx for Graph API

## Phase 3 – Job queue & persistence
- [ ] SQLite schema + migrations (jobs, processed_messages)
- [ ] Job statuses: queued, running, waiting_approval, done, failed, cancelled
- [ ] asyncio worker (configurable concurrency), retry with backoff, max attempts
- [ ] "stop" command cancels the running job (task cancel + status)
- [ ] Dedup moved to SQLite; worker survives restart (requeue `running` on startup)

## Phase 4 – STT
- [ ] `Transcriber` protocol, `FasterWhisperTranscriber` (CPU, int8, lazy model load)
- [ ] Download voice note (.ogg) via Graph API media endpoint, size limit
- [ ] Language autodetect restricted to pl/de/en; result text goes to job queue
- [ ] Unit tests with fake transcriber; integration test with a tiny audio sample

## Phase 5 – LLM client
- [ ] `LLMClient` protocol (chat with messages + tools -> text / tool calls)
- [ ] `OpenAICompatClient` (base_url, model, api_key, timeouts) via httpx
- [ ] Error mapping: timeout, rate limit, server, bad response; limited retries
- [ ] `MockLLM` with scripted responses (incl. tool calls) for tests

## Phase 6 – Sandbox
- [ ] `Dockerfile.sandbox` (git, pytest, ruff, non-root)
- [ ] `DockerSandbox.run(cmd)`: `--network none`, `--cpus`, `--memory`, `--pids-limit`,
      read-only root, `/workspace` volume, timeout + kill, output truncation
- [ ] `SandboxResult` (exit code, stdout/stderr, truncated, timed_out)
- [ ] Unit tests on command building; integration tests with real Docker

## Phase 7 – Agent loop
- [ ] Tool registry with JSON schemas
- [ ] Tools: shell (sandbox), read_file, write_file, git, http_get (domain allowlist)
- [ ] Path guard: everything resolved inside `/workspace` (no `..`, no symlink escape)
- [ ] Loop: LLM -> tool calls -> results, step limit, token/output caps
- [ ] Final summary sent to WhatsApp; progress updates throttled

## Phase 8 – Approval gate
- [ ] Risk classifier for actions (git push, deploy, delete, spending, unknown network)
- [ ] `ApprovalGate.request()` -> WhatsApp prompt, waits for TAK/NIE, timeout = deny
- [ ] Job status `waiting_approval`; answers matched to the pending request
- [ ] Tests with fake sender and controlled clock

## Phase 9 – Free-API router
- [ ] `providers.yaml` (Groq, Gemini, OpenRouter, Mistral, …): base_url, model, key env, limits
- [ ] Router implements `LLMClient`: priority order, fallback on error/limit
- [ ] Per-provider rate limiting (rpm/rpd), request counters in SQLite
- [ ] Response cache (hash of request, TTL)

## Phase 10 – Memory & "learning"
- [ ] Q/A store with quality rating (owner feedback / heuristics)
- [ ] `Embedder` protocol + simple implementation; cosine search over SQLite blobs
- [ ] RAG: search memory before calling external API, inject top-k context
- [ ] JSONL export (chat format) filtered by rating for future fine-tuning

## Phase 11 – Deployment
- [ ] docker-compose: app + vLLM service (GPU optional), volumes, healthchecks
- [ ] `deploy/start.sh`, systemd unit
- [ ] README: setup steps (Meta app, webhook, .env, run), troubleshooting
- [ ] Security checklist (secrets, firewall, HTTPS, sandbox, backups)

## Phase 12 – TTS (optional, only on request)
- [ ] `Synthesizer` protocol, voice replies as WhatsApp audio
