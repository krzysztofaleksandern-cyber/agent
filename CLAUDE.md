# CLAUDE.md

Private, autonomous coding agent running 24/7 on a cloud server. The owner talks to it
over WhatsApp (text + voice notes); it plans, runs tools in a Docker sandbox, asks for
approval before risky actions and reports back. The LLM itself is **not** part of this
repo: we ship an OpenAI-compatible client (vLLM, free APIs) and a mock for tests.

## Stack
- Python 3.12, FastAPI + uvicorn, httpx, pydantic-settings
- SQLite via stdlib `sqlite3` (wrapped with `asyncio.to_thread`) — no ORM
- Docker CLI (subprocess) for the sandbox — no Docker SDK
- faster-whisper (optional extra `stt`), PyYAML (provider config)
- Dev: pytest, pytest-asyncio, respx (httpx mocking), ruff, pre-commit

## Layout
```
src/agent/
  config.py          Settings (env / .env), single source of configuration
  logging.py         JSON logging + secret/message redaction
  main.py            FastAPI app factory, lifespan wiring, /health
  whatsapp/          webhook (verify, signature, whitelist, dedup), sender (chunking)
  jobs/              SQLite store, job model/statuses, asyncio worker, retry, cancel
  stt/               Transcriber protocol, FasterWhisperTranscriber, audio helpers
  llm/               LLMClient protocol, OpenAICompatClient, MockLLM, errors
  router/            YAML providers, fallback, rate limits, counters, response cache
  sandbox/           DockerSandbox: no network, CPU/RAM/PID limits, timeout, output cap
  agent_loop/        tool registry, tools (shell, files, git, http_get), loop, summary
  approvals/         ApprovalGate: risky actions -> WhatsApp YES/NO, timeout = deny
  memory/            Q/A store, Embedder protocol, vector search (RAG), JSONL export
tests/               mirrors src/agent/, one test module per source module
deploy/              systemd unit, start script
```

## Architecture rules
- Every external dependency sits behind a `typing.Protocol` (Transcriber, LLMClient,
  Embedder, Sandbox, MessageSender). Concrete classes are wired only in `main.py`.
- Modules depend inward: `whatsapp` -> `jobs` -> `agent_loop` -> (`llm`, `sandbox`,
  `approvals`, `memory`). No cycles; no module imports `main.py`.
- All I/O is async. Blocking calls (sqlite, whisper) go through `asyncio.to_thread`.
- Config is read once into `Settings`; modules receive what they need via constructor.

## Conventions
- Code, comments, commit messages: English. Talk to the owner: Polish.
- Full type hints; `ruff check` + `ruff format` clean; line length 100.
- Small modules, pure functions where possible, dependency injection over globals.
- Tests: pytest, no network, no real Docker/whisper/LLM in unit tests (mark those
  `@pytest.mark.integration`, skipped by default).
- Secrets only in `.env` (git-ignored); every new setting goes to `.env.example`.
- Never log secrets or full message bodies: use `redact()` / `preview()` from `logging.py`.
- No new dependency without a clear reason; prefer stdlib.

## Commands
```bash
pip install -e ".[dev]"            # add ,stt for faster-whisper
pytest                             # unit tests
pytest -m integration              # needs Docker etc.
ruff check . && ruff format --check .
pre-commit install
uvicorn agent.main:app --reload    # local dev
docker compose up --build          # full stack
```

## Workflow
- Work phase by phase from TASKS.md. Done = tests green, ruff clean, docs updated, commit.
- Stop after each phase and wait for the owner's "dalej".
- Open only files you need; no refactors outside the current phase.
- Max 3 attempts at the same failure, then ask.
