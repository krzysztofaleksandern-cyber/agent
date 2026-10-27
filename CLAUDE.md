# CLAUDE.md

Private, autonomous coding agent (Python 3.12, FastAPI) running 24/7 on a cloud server.
The owner talks to it via WhatsApp (text + voice notes). The LLM itself is **not** part of
this repo: we ship an OpenAI-compatible client (configurable `base_url` / `model` / key)
and a mock for tests.

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
  main.py            FastAPI app factory, lifespan, dependency wiring, /health
  config.py          Settings (pydantic-settings, reads env / .env)
  logging.py         JSON-ish logging setup + secret/message redaction
  gateway/whatsapp/  Phase 2: webhook (GET verify, POST events), signature check,
                     owner allowlist, dedup, Cloud API sender (chunked text)
  tasks/             Phase 3: SQLite task store, asyncio worker, statuses, retry, cancel
  stt/               Phase 4: Transcriber protocol, faster-whisper impl (CPU, int8)
  llm/               Phase 5: LLMClient protocol, OpenAI-compatible impl (httpx), MockLLM
  sandbox/           Phase 6: one-shot Docker runner (no network, CPU/RAM/PID limits)
  agent/             Phase 7: tool-calling loop, tools (shell, files, git, http_get),
                     path jail to /workspace, step limit, final summary
  approvals/         Phase 8: risky-action gate, YES/NO via WhatsApp, timeout = deny
  router/            Phase 9: free-API provider router (YAML), fallback, rate limit,
                     usage counter, response cache
  memory/            Phase 10: Q/A store + Embedder protocol, RAG lookup, JSONL export
deploy/              Phase 11: compose (app + vLLM), start script, systemd unit
tests/               pytest, mirrors app/ layout; no network, no real Docker/LLM by default
```

Data flow: WhatsApp → `/webhook` → verify signature + owner allowlist + dedup →
(voice → STT) → task queue (SQLite) → worker → agent loop (LLM via router/client,
tools in sandbox, risky actions via approval gate) → reply via WhatsApp sender.

## Conventions

- Python 3.12 target (`requires-python = ">=3.12"`), `from __future__ import annotations` not needed.
- Async-first (FastAPI, httpx.AsyncClient). Blocking work (sqlite3, whisper, docker CLI)
  goes through `asyncio.to_thread` / `asyncio.create_subprocess_exec`.
- SQLite via stdlib `sqlite3` (no ORM). Docker via the `docker` CLI (no docker SDK).
- Settings are injected, never read from `os.environ` deep in the code.
- Tests: `pytest` + `pytest-asyncio` (auto mode); external services are faked
  (`httpx.MockTransport`, MockLLM, fake runner). Tests needing real Docker are marked
  `@pytest.mark.docker` and skipped by default.
- Lint/format: `ruff check` + `ruff format` (config in `pyproject.toml`).

## Dependencies (keep minimal)

Runtime: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `httpx`, `pyyaml` (phase 9).
Optional extra `stt`: `faster-whisper`. Dev: `pytest`, `pytest-asyncio`, `ruff`, `pre-commit`.

## Commands

```bash
uv venv && uv pip install -e ".[dev]"     # or: pip install -e ".[dev]"
pytest -q                                  # tests
ruff check . && ruff format --check .      # lint
uvicorn app.main:create_app --factory --reload   # dev server
docker compose up --build                  # container run
```
