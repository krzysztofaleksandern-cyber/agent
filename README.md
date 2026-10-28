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

## API keys

```bash
python -m app.cli secret                  # paste into .env as ADMIN_API_KEY
python -m app.cli keys create my-bot      # key for a client app, shown once
python -m app.cli keys list
python -m app.cli keys revoke <id>
```

## Using the API (OpenAI-compatible)

```python
from openai import OpenAI
client = OpenAI(base_url="http://<server>:8080/v1", api_key="sk-dev-...")
client.chat.completions.create(model="coder", messages=[{"role": "user", "content": "Hi"}])
```

Endpoints: `POST /v1/chat/completions` (incl. `stream: true`), `GET /v1/models`,
`GET /v1/admin/usage` (admin key).

## Docker

```bash
docker compose up --build     # app on 127.0.0.1:8080
```

Full deployment guide and security checklist: Phase 11.
