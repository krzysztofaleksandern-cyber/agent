# devagent

Private, self-hosted AI agent platform. Open-weight models run on **your own GPU** via
Ollama; your apps (bots, TTS, websites) connect through an **OpenAI-compatible API**.
Agents (`orchestrator`, `codex`, `writer`, `auditor`, or your own) have their own prompt,
model and tools, work in a Docker sandbox, ask for approval before risky actions,
remember lessons and good answers, and can be fine-tuned on your rated conversations.
No paid APIs, no moderation layer.

Architecture and conventions: `CLAUDE.md`. Roadmap/status: `TASKS.md`.

```
your apps ──HTTPS──► VPS (24/7, ~5 €/mo)                      GPU box (Vast.ai)
                     ├─ API /v1/* (keys)                       ├─ Ollama (models)
                     ├─ agents + tool loop ──Tailscale tunnel──►└─ training (QLoRA)
                     ├─ Docker sandbox (no network)
                     └─ SQLite: tasks, memory, versions
```

## 1. GPU box (Vast.ai)

1. Rent an instance (RTX 3090/3090 Ti/4090 24 GB recommended for training; V100S 32 GB
   if you need bigger models). Use a PyTorch/CUDA template, disk ≥ 100 GB.
   **Stop** the instance when idle - never *destroy* it (that deletes models and data).
2. Create a Tailscale auth key (tailscale.com → Settings → Keys) and set it as `TS_AUTHKEY`
   in the instance environment.
3. Clone this repo to `/workspace/agent` and use `deploy/gpu/onstart.sh` as the on-start
   script. It installs Tailscale (userspace mode), Ollama (models in `/workspace/ollama`,
   bound to localhost, reachable only via the tunnel) and pulls the models.

| GPU | Recommended `config/models.yaml` |
|---|---|
| 24 GB (RTX 3090 Ti) | `coder: qwen2.5-coder:14b`, `general: qwen2.5:14b` (default config) |
| 32 GB (V100S) | `coder: qwen2.5-coder:32b` (q4), `general: qwen2.5:14b` |

## 2. VPS

Any small Linux VPS (2 vCPU / 4 GB RAM is enough, e.g. Hetzner CX22) with Docker.

```bash
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
git clone <this repo> /opt/devagent && cd /opt/devagent
cp .env.example .env
python3 -m venv .venv && .venv/bin/pip install -e .      # for the admin CLI
.venv/bin/python -m app.cli secret     # -> ADMIN_API_KEY in .env
.venv/bin/python -m app.cli secret     # -> WEBHOOK_SECRET in .env
# .env: OLLAMA_URL=http://<gpu-tailscale-ip>:11434, DOMAIN=ai.example.com, APPROVAL_WEBHOOK_URL=...
./deploy/vps/start.sh
sudo cp deploy/vps/devagent.service /etc/systemd/system/ && sudo systemctl enable --now devagent
```

Client keys for your apps (run where the DB lives, e.g. inside the container):

```bash
docker compose -f deploy/vps/docker-compose.yml exec app python -m app.cli keys create my-bot
docker compose -f deploy/vps/docker-compose.yml exec app python -m app.cli keys list
docker compose -f deploy/vps/docker-compose.yml exec app python -m app.cli keys revoke 1
```

Backups: add `deploy/vps/backup.sh` to cron (daily SQLite backup, 14 days retention).

## 3. Using it from your apps

```python
from openai import OpenAI

ai = OpenAI(base_url="https://ai.example.com/v1", api_key="sk-dev-...")
r = ai.chat.completions.create(model="codex", messages=[{"role": "user", "content": "..."}])
print(r.choices[0].message.content)
# rate the answer -> the platform learns
# POST /v1/feedback {"interaction_id": r.model_extra["interaction_id"], "rating": 5}
```

| Endpoint | Who | Purpose |
|---|---|---|
| `POST /v1/chat/completions` | client key | agent (`model`=agent name) or raw model alias; `stream` supported |
| `GET /v1/models` | client key | agents + model aliases |
| `POST /v1/tasks`, `GET /v1/tasks[/{id}]`, `POST /v1/tasks/{id}/cancel` | client key | long jobs in background, signed webhook on completion |
| `POST /v1/feedback` | client key | rate an answer 1-5 (+ comment = correction lesson) |
| `GET /v1/approvals`, `POST /v1/approvals/{id}` | admin | answer TAK/NIE for risky actions |
| `GET/PUT /v1/admin/agents[/{name}]` | admin | view / create / edit agents |
| `GET/POST/DELETE /v1/admin/lessons` | admin | owner rules (always applied) and learned lessons |
| `GET /v1/admin/usage` | admin | requests / tokens / errors per model |
| `GET /v1/admin/dataset`, `POST /v1/admin/candidates`, `GET /v1/admin/versions`, `POST /v1/admin/versions/{alias}/rollback` | admin | fine-tuning cycle |

Webhooks (task results, `approval.requested`) carry `X-Devagent-Signature: sha256=<HMAC of
body with WEBHOOK_SECRET>`; verify with `app.tasks.webhook.verify()` logic.

Approval flow for your bot: receive `approval.requested` → ask the owner "TAK/NIE?" →
`POST /v1/approvals/{id}` with `{"answer": "TAK"}`. No answer within `APPROVAL_TIMEOUT`
= refused.

## 4. Learning

- Every agent answer is stored with an `interaction_id`.
- Ratings ≥ 4 make answers few-shot examples for similar future tasks (RAG).
- Rating ≤ 2 with a comment turns the comment into a lesson for that agent.
- After each task the agent writes itself a short lesson (`MEMORY_REFLECT`).
- Your own rules: `POST /v1/admin/lessons {"agent": "*", "text": "..."}` - always applied.
- Fine-tuning on the GPU box: see `training/README.md` (dataset → QLoRA → Ollama →
  automatic eval → promote or reject; rollback anytime).

## Development

```bash
uv venv && uv pip install -e ".[dev]" && pre-commit install
pytest -q && ruff check . && ruff format --check .
SANDBOX_BACKEND=local MEMORY_EMBEDDER=hash uvicorn app.main:create_app --factory --reload
```

`SANDBOX_BACKEND=local` runs agent commands on your machine **without isolation** -
development only.

## Security checklist

- [ ] `.env` is not committed; `ADMIN_API_KEY` and `WEBHOOK_SECRET` generated with `app.cli secret`.
- [ ] One client key per app; revoke unused ones (`keys list` shows last use).
- [ ] API only via HTTPS (Caddy); port 8080 bound to 127.0.0.1; firewall allows only 22/80/443.
- [ ] Ollama is bound to localhost on the GPU box and reachable only via Tailscale; no Vast
      port mapping for 11434.
- [ ] Sandbox image built (`devagent-sandbox`); `SANDBOX_BACKEND=docker` in production.
- [ ] The app container has the Docker socket (needed to start sandboxes) - that is
      root-equivalent on the VPS: use a dedicated VPS for this platform, keep it updated,
      SSH with keys only. (Rootless Docker is a stronger option.)
- [ ] `APPROVAL_MODE=risky`, `APPROVAL_WEBHOOK_URL` set, approvals answered only by you.
- [ ] `HTTP_ALLOWLIST` limited to domains the agents really need (content fetched from
      the web can try to manipulate the agent - prompt injection).
- [ ] Git credentials given to the sandbox (if any) are deploy keys with minimal scope.
- [ ] Vast.ai: prefer "Secure Cloud" (datacenter) offers for private data; stop, don't destroy.
- [ ] Daily backups (`backup.sh`) copied off the VPS.
- [ ] `config/eval.yaml` contains your real tasks before enabling automatic fine-tuning.
