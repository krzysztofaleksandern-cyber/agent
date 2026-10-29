"""devagent host worker — runs on the OWNER'S OWN Windows computer.

It opens no inbound port: it long-polls the VPS for commands, runs them locally
(mouse, keyboard, screenshot, PowerShell, files) and posts results back. You start it
yourself, under your own account. Stop it any time with Ctrl+C.

Config via environment (or a .env next to this file):
    DEVAGENT_URL           e.g. https://ai.example.com
    OPERATOR_WORKER_TOKEN  same value as on the VPS

    pip install -r worker/requirements.txt
    python worker/operator_worker.py
"""

import base64
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def _load_env_file() -> None:
    """Load KEY=VALUE lines from a .env next to this script (for autostart, no shell env)."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

URL = os.environ.get("DEVAGENT_URL", "http://127.0.0.1:8080").rstrip("/")
TOKEN = os.environ.get("OPERATOR_WORKER_TOKEN", "")
SHOTS_DIR = Path(os.environ.get("DEVAGENT_SHOTS", Path.home() / ".devagent" / "shots"))
MAX_OUTPUT = 20_000

try:
    import pyautogui

    pyautogui.FAILSAFE = False
except Exception:
    pyautogui = None


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n…[truncated]"


def _need_gui() -> Any:
    if pyautogui is None:
        raise RuntimeError("pyautogui is not installed (pip install -r worker/requirements.txt)")
    return pyautogui


def screenshot(_: dict) -> dict:
    gui = _need_gui()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    img = gui.screenshot()
    w, h = img.size
    # downscale so the base64 payload stays small for the vision model
    max_w = 1280
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)))
    path = SHOTS_DIR / f"shot-{int(time.time() * 1000)}.png"
    img.save(path)
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"output": f"screen {w}x{h}", "image_b64": b64}


def mouse_move(p: dict) -> str:
    _need_gui().moveTo(int(p["x"]), int(p["y"]))
    return f"moved to {p['x']},{p['y']}"


def mouse_click(p: dict) -> str:
    gui = _need_gui()
    kw = {"button": p.get("button", "left")}
    if "x" in p and "y" in p:
        kw |= {"x": int(p["x"]), "y": int(p["y"])}
    (gui.doubleClick if p.get("double") else gui.click)(**kw)
    return "clicked"


def mouse_scroll(p: dict) -> str:
    _need_gui().scroll(int(p["amount"]))
    return "scrolled"


def type_text(p: dict) -> str:
    _need_gui().write(str(p["text"]), interval=0.01)
    return f"typed {len(str(p['text']))} chars"


def key_press(p: dict) -> str:
    gui = _need_gui()
    keys = [k.strip() for k in str(p["keys"]).replace("+", " ").split()]
    gui.hotkey(*keys) if len(keys) > 1 else gui.press(keys[0])
    return f"pressed {p['keys']}"


def os_run(p: dict) -> str:
    target = str(p["target"])
    args = [str(a) for a in p.get("args", [])]
    os.startfile(target) if not args else subprocess.Popen([target, *args])  # noqa: S603,S606
    return f"launched {target}"


def os_shell(p: dict) -> str:
    completed = subprocess.run(  # noqa: S603
        ["powershell", "-NoProfile", "-Command", str(p["command"])],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=float(p.get("timeout", 120)),
    )
    return _clip(f"exit={completed.returncode}\n{completed.stdout}{completed.stderr}")


def os_read_file(p: dict) -> str:
    return _clip(Path(p["path"]).read_text(errors="replace"))


def os_write_file(p: dict) -> str:
    path = Path(p["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(p["content"]))
    return f"wrote {len(str(p['content']))} chars to {path}"


def os_list_dir(p: dict) -> str:
    root = Path(p["path"])
    return "\n".join(sorted(e.name + ("/" if e.is_dir() else "") for e in root.iterdir()))


HANDLERS = {
    "screenshot": screenshot,
    "mouse_move": mouse_move,
    "mouse_click": mouse_click,
    "mouse_scroll": mouse_scroll,
    "type_text": type_text,
    "key_press": key_press,
    "os_run": os_run,
    "os_shell": os_shell,
    "os_read_file": os_read_file,
    "os_write_file": os_write_file,
    "os_list_dir": os_list_dir,
}


def execute(action: str, params: dict) -> dict:
    handler = HANDLERS.get(action)
    if handler is None:
        return {"ok": False, "error": f"unknown action {action}"}
    try:
        return {"ok": True, "output": handler(params)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    if not TOKEN:
        print("set OPERATOR_WORKER_TOKEN (same as on the VPS)", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bearer {TOKEN}"}
    print(f"devagent worker connecting to {URL} (Ctrl+C to stop)")
    with httpx.Client(base_url=URL, headers=headers, timeout=40) as client:
        while True:
            try:
                cmd = client.post("/v1/operator/poll").json().get("command")
                if cmd is None:
                    continue
                result = execute(cmd["action"], cmd.get("params", {}))
                client.post("/v1/operator/result", json={"id": cmd["id"], **result})
            except httpx.HTTPError as exc:
                print(f"connection error: {type(exc).__name__}; retrying in 5s", file=sys.stderr)
                time.sleep(5)
            except KeyboardInterrupt:
                print("\nstopped")
                return 0


if __name__ == "__main__":
    sys.exit(main())
