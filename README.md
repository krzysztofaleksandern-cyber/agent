# devagent

Private, self-hosted AI agent platform (Python 3.12, FastAPI). Open-weight models run on
your own GPU via Ollama (or vLLM); your apps connect through an OpenAI-compatible API.
See `CLAUDE.md` for architecture and `TASKS.md` for the roadmap.

## Models

Backends and model aliases live in `config/models.yaml` (fallback chains supported).
On the GPU box: `ollama pull qwen2.5-coder:14b` etc., then set `OLLAMA_URL` in `.env`.

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
