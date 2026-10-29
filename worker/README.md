# devagent host worker (control your own computer)

Runs on **your** Windows PC and lets the `operator` agent act on it (mouse, keyboard,
screenshots, PowerShell, files). It connects **out** to your VPS — no inbound port, no
remote-desktop server. You start it; Ctrl+C stops it. Risky actions (shell, launching
programs, writing/deleting files) still require your TAK/NIE confirmation from the phone.

## Install

```powershell
git clone -b claude/hej-o5fsco https://github.com/krzysztofaleksandern-cyber/agent.git
cd agent
py -m pip install -r worker/requirements.txt
$env:DEVAGENT_URL = "https://ai.example.com"
$env:OPERATOR_WORKER_TOKEN = "<same token as on the VPS>"
py worker/operator_worker.py
```

When it prints "connecting", send the `operator` agent a task from your phone. Check it is
linked: `GET /v1/operator/status` (admin key) → `{"online": true, ...}`.

## Autostart (optional)

Create a shortcut to `py worker/operator_worker.py` (with the two env vars set as user
environment variables) in `shell:startup`, or wrap it as a service with NSSM.

## Safety

- The worker has the full rights of your Windows user. Run it only while you want the agent
  to be able to act, and stop it otherwise.
- Keep `OPERATOR_WORKER_TOKEN` secret; rotate it (regenerate on the VPS and here) if leaked.
- The VPS only ever reaches your PC through this outbound connection you initiated.

## Autostart at logon (recommended)

So the computer is always reachable by Jarvis without you launching anything:

```powershell
copy worker\.env.example worker\.env    # then edit worker\.env (URL + token)
powershell -ExecutionPolicy Bypass -File worker\install_autostart.ps1
```

This registers a hidden Scheduled Task `devagent-worker` that starts at every logon and
restarts itself if it crashes. It reads `worker\.env` (no shell variables needed).

```powershell
Stop-ScheduledTask  -TaskName devagent-worker      # pause now
Start-ScheduledTask -TaskName devagent-worker      # resume
powershell -File worker\uninstall_autostart.ps1    # remove autostart
```

Security: while the task runs, Jarvis can act on your PC (risky actions still need your
TAK/NIE from the phone). Uninstall or `Stop-ScheduledTask` whenever you want it fully off.
