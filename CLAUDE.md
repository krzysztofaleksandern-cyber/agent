# CLAUDE.md

Private, self-hosted AI agent platform (Python 3.12, FastAPI). No paid APIs: models are
open-weight, served by **Ollama** (or vLLM) on a rented GPU (Vast.ai). The owner's own apps
(bots, TTS, etc.) connect through this platform's **OpenAI-compatible API**, where
`model` = agent name. Agents (jarvis, orchestrator, codex, writer, auditor, operator, secretary, researcher) each have their own
prompt, model and tools; the orchestrator delegates to the others. The platform learns from
history, ratings and self-written lessons (RAG) and periodically fine-tunes LoRA adapters.
No content-moderation layer; API keys stay (security, not limits).

Deployment topology: cheap VPS 24/7 (this app, agents, memory, Docker sandbox) + Vast.ai GPU
instance (Ollama + training) reached over a WireGuard/Tailscale tunnel. Vast instances are
containers themselves, so Docker sandboxing must live on the VPS.

## Working rules (owner's instructions)

- Communicate with the owner in **Polish**; code, comments, commit messages in **English**.
- Work in phases from `TASKS.md`. After each phase: tests green, ruff clean, docs updated,
  commit, 5-sentence summary, then **STOP and wait for "dalej"**.
- Limited budget: open only files you need, no refactors outside the current phase,
  max 3 attempts at fixing the same error, then ask the owner.
- Small, testable modules, type hints everywhere, no unnecessary dependencies.
- Secrets only in `.env` (template in `.env.example`). Never log API keys, tokens or full
  message bodies — use `app.logging.redact()` / truncated previews.

## Architecture

Every subsystem is a module behind a small interface (`typing.Protocol` or ABC) so it can be
swapped or mocked. Wiring happens in one place: `app/main.py` (`create_app()` + lifespan).

```
app/
  main.py        FastAPI app factory, lifespan, dependency wiring, /health
  config.py      Settings (pydantic-settings, reads env / .env)
  logging.py     logging setup + secret/message redaction
  llm/           Phase 2: LLMClient protocol, OpenAI-compatible client (Ollama/vLLM),
                 MockLLM, model registry (models.yaml) with fallback, usage meter,
                 Ollama admin (list/pull models)
  api/           Phase 3: public OpenAI-compatible API (/v1/chat/completions, /v1/models,
                 streaming), per-app API keys (hashed, SQLite)
  agents/        Phase 4: agent profiles (agents.yaml: prompt, model, tools)
  tasks/         Phase 5: SQLite task store, asyncio worker, statuses, retry, cancel, webhooks
  sandbox/       Phase 6: one-shot Docker runner (no network, CPU/RAM/PID limits)
  tools/         Phase 6: shell, read/write file, git, http_get (domain allowlist), path jail
  agent/         Phase 7: tool-calling loop, step limit, delegation between agents
  approvals/     Phase 8: risky-action gate via API, timeout = deny
  memory/        Phase 9: history, ratings, lessons, Embedder (Ollama embeddings), RAG
  operator/      Phase 13: command channel to the host worker controlling the owner's PC
  console/       Phase 14: phone PWA (OTP login) to drive the operator agent + approvals
  connectors/    Phase 16+: office connectors (email IMAP/SMTP; calendar, …) behind interfaces
  audit/         Phase 18: durable log of every tool action (admin + console)
  scheduler/     Phase 19: recurring jobs (daily/weekly/interval) -> agent tasks
  learning/      Phase 10: dataset builder, LoRA training job, model versioning, eval, rollback
config/          models.yaml, agents.yaml, eval.yaml
training/        GPU-box fine-tuning (Unsloth QLoRA) + run_cycle.sh
worker/          Phase 13: host worker for the owner's Windows computer (pyautogui)
deploy/          Phase 11: compose for VPS and GPU, tunnel, systemd, security checklist
tests/           pytest; no network, no real Docker/LLM by default
```

Data flow: client app → `/v1/chat/completions` (API key) → agent profile → agent loop
(memory/RAG context → LLM via registry → tools in sandbox, risky actions via approval gate,
delegation to other agents) → response (sync, stream, or task + webhook) → history for learning.

## Conventions

- Python 3.12 target (`requires-python = ">=3.12"`), `from __future__ import annotations` not needed.
- Async-first (FastAPI, httpx.AsyncClient). Blocking work (sqlite3, docker CLI)
  goes through `asyncio.to_thread` / `asyncio.create_subprocess_exec`.
- SQLite via stdlib `sqlite3` (no ORM). Docker via the `docker` CLI (no docker SDK).
- Settings are injected, never read from `os.environ` deep in the code.
- Tests: `pytest` + `pytest-asyncio` (auto mode); external services are faked
  (`httpx.MockTransport`, MockLLM, fake runner). Tests needing real Docker are marked
  `@pytest.mark.docker` and skipped by default.
- Lint/format: `ruff check` + `ruff format` (config in `pyproject.toml`).

## Dependencies (keep minimal)

Runtime: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `httpx`, `pyyaml`.
Training (GPU box only, separate image): `unsloth`/`peft`, `transformers`.
Dev: `pytest`, `pytest-asyncio`, `ruff`, `pre-commit`.

## Commands

```bash
uv venv && uv pip install -e ".[dev]"     # or: pip install -e ".[dev]"
pytest -q                                  # tests
ruff check . && ruff format --check .      # lint
uvicorn app.main:create_app --factory --reload   # dev server
docker compose up --build                  # local container run
./deploy/vps/start.sh                      # production stack on the VPS (see README)
```
