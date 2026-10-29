# devagent — full assembly guide ("jak to wszystko pospinać")

This is the end-to-end guide to run the whole system: the AI platform, the models, the voice
layer, Jarvis and the office agents, and control of your own computer from your phone.

Everything is **yours and private**: open-weight models on your own GPU, your own API, no
third-party AI in the loop (Gemini is optional and only if you add keys).

---

## 0. The picture

```
          PHONE (you, anywhere)
            │  voice / text
            ▼
   ┌───────────────────────────────┐        ┌──────────────────────┐
   │  VPS  (24/7, ~5 €/mo)          │        │  GPU box (Vast.ai)   │
   │  • API  /v1/* + /console (PWA) │──tunnel─►  • Ollama (models)   │
   │  • Jarvis + all agents        │        │  • LoRA training     │
   │  • tasks, memory, learning    │        └──────────────────────┘
   │  • Docker sandbox (for code)  │
   │  • approvals (TAK/NIE)        │        ┌──────────────────────┐
   └──────────────┬────────────────┘──tunnel─►  YOUR Windows PC     │
                  │                         │  • host worker       │
          VoiceStudio (your voice: TTS,     │  • VoiceStudio app   │
          cloning, dubbing — local app)     └──────────────────────┘
```

Three machines, each doing what it is good at:
- **VPS** — always on, cheap, holds the brain and the API.
- **GPU box** — rented by the hour, runs the models and the training.
- **Your PC** — where Jarvis actually clicks, types and talks (via the worker + VoiceStudio).

---

## 1. GPU box (models) — Vast.ai

1. Rent an instance (RTX 3090/3090 Ti/4090 24 GB for training; V100S 32 GB for bigger
   models). PyTorch/CUDA template, disk ≥ 100 GB. **Stop** when idle, never **destroy**.
2. Tailscale auth key → set `TS_AUTHKEY` in the instance env.
3. Clone the repo to `/workspace/agent`, use `deploy/gpu/onstart.sh` as the on-start script.
   It installs Tailscale (userspace) + Ollama (localhost only) and pulls the models.
4. Models per GPU: see `README.md` table and `config/models.yaml`.

## 2. VPS (brain + API)

```bash
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
git clone -b claude/hej-o5fsco https://github.com/krzysztofaleksandern-cyber/agent.git /opt/devagent
cd /opt/devagent
cp .env.example .env
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m app.cli secret   # -> ADMIN_API_KEY in .env
.venv/bin/python -m app.cli secret   # -> WEBHOOK_SECRET in .env
.venv/bin/python -m app.cli secret   # -> OPERATOR_WORKER_TOKEN in .env
# edit .env: OLLAMA_URL=http://<gpu-tailscale-ip>:11434, DOMAIN=ai.example.com,
#            GEMINI_API_KEYS=... (optional), APPROVAL_WEBHOOK_URL=... (your voice bot)
./deploy/vps/start.sh
sudo cp deploy/vps/devagent.service /etc/systemd/system/ && sudo systemctl enable --now devagent
```

Public address without opening ports: install **Cloudflare Tunnel** (`cloudflared`) on the
VPS pointing at `127.0.0.1:8080`, map it to `ai.example.com`. (Cloudflare *Workers* are not
used — they can't hold the long-running app or SQLite.)

## 3. Your Windows PC (hands + voice)

```powershell
git clone -b claude/hej-o5fsco https://github.com/krzysztofaleksandern-cyber/agent.git
cd agent
py -m pip install -r worker\requirements.txt
copy worker\.env.example worker\.env      # set DEVAGENT_URL + OPERATOR_WORKER_TOKEN
powershell -ExecutionPolicy Bypass -File worker\install_autostart.ps1
```

The worker now starts at every logon and lets Jarvis use your PC. Confirm:
`GET /v1/operator/status` (admin key) → `{"online": true}`.

Install **VoiceStudio** on the same PC (your local ElevenLabs alternative from the video) for
voice cloning / TTS / dubbing. It stays fully local; no keys, no cloud.

## 4. Phone (you)

1. Get a one-time code on the VPS: `python -m app.cli console-otp`.
2. Open `https://ai.example.com/console/` in Chrome → enter the code → "Add to home screen".
3. Type (or speak — see voice below) a task. Jarvis routes it. Approvals pop up as TAK/NIE.

---

## 5. The voice loop (Jarvis that talks)

You already have the voice pieces; wire them, don't rebuild them:

- **You speak → text:** your existing WhatsApp voice agent (or any STT) turns speech into
  text and calls `POST /v1/chat/completions` with `model: "jarvis"`.
- **Jarvis thinks and acts:** delegates to operator/secretary/codex/etc.
- **Text → voice (reply):** send Jarvis's answer to **VoiceStudio** (your cloned voice) and
  play it back. VoiceStudio runs on the PC the operator already controls, so Jarvis can even
  drive it via the operator, or you call VoiceStudio directly from your voice app.

So: phone mic → STT → `jarvis` → VoiceStudio TTS → phone speaker. All local.

---

## 6. Who's who (the agents)

| Agent | Does |
|---|---|
| **jarvis** | your chief of staff; routes anything to the right specialist |
| **secretary** | email, calendar, documents, office admin (via the operator) |
| **operator** | clicks, types, screenshots, shell, files on your Windows PC |
| **codex** | writes/fixes/tests/ships code in a sandbox; git |
| **writer** | texts, docs, translations PL/DE/EN |
| **auditor** | reviews websites, code, configs (security, SEO, quality) |
| **researcher** | web research + sourced summaries |
| **orchestrator** | the original lightweight router (codex/writer/auditor) |

Add or edit agents anytime: `config/agents.yaml` or `PUT /v1/admin/agents/{name}` — no code.

## 7. Daily use

- Talk/type to **jarvis** for anything.
- It **learns**: rate answers (`POST /v1/feedback`), good ones come back as examples; your
  rules (`POST /v1/admin/lessons {"agent":"*","text":"..."}`) always apply; weekly LoRA
  training on the GPU box (`training/README.md`).
- Risky actions always wait for your **TAK/NIE** on the phone.

## 8. Checklists

- Setup done: `/health` ok, `/v1/operator/status` online, a test task to `jarvis` returns.
- Security: see the checklist at the end of `README.md` (HTTPS, worker token, localhost-only
  Ollama, approvals on, HTTP allowlist, backups, stop the worker when not needed).
