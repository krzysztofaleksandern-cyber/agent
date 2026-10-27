# devagent

Private, autonomous coding agent (Python 3.12, FastAPI) controlled via WhatsApp.
The LLM is pluggable: any OpenAI-compatible endpoint (e.g. vLLM). See `CLAUDE.md` for
architecture and `TASKS.md` for the roadmap.

## Quick start (dev)

```bash
cp .env.example .env          # fill in values
uv venv && uv pip install -e ".[dev]"
pre-commit install
pytest -q && ruff check .
uvicorn app.main:create_app --factory --reload
curl localhost:8000/health
```

## Docker

```bash
docker compose up --build     # app on 127.0.0.1:8080
```

Full deployment guide and security checklist: Phase 11.
