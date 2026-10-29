"""End-to-end: operator vision. The worker's screenshot result (with image_b64) must pass
through the real /v1/operator/result endpoint and reach the model as an image_url block."""

import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

import httpx

from app.config import Settings
from app.llm.registry import ModelRegistry, load_config
from app.llm.types import LLMResponse, ToolCall, Usage
from app.main import create_app

WTOK = "wtok-e2e"


def load_worker(tmp_path):
    """Import worker/operator_worker.py with a fake pyautogui so screenshot() works headless."""
    fake = types.ModuleType("pyautogui")

    class _Img:
        size = (100, 100)

        def resize(self, size):
            return self

        def save(self, path):
            Path(path).write_bytes(b"\x89PNGfakeimage")

    fake.screenshot = lambda: _Img()
    fake.FAILSAFE = False
    sys.modules["pyautogui"] = fake
    os.environ["DEVAGENT_SHOTS"] = str(tmp_path / "shots")
    path = Path(__file__).resolve().parent.parent / "worker" / "operator_worker.py"
    spec = importlib.util.spec_from_file_location("operator_worker_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _has_image(messages) -> bool:
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "image_url" for b in content
        ):
            return True
    return False


async def test_operator_vision_end_to_end(tmp_path) -> None:
    worker = load_worker(tmp_path)

    # 1) worker.execute must surface image_b64 at the top level (not nested in output).
    res = worker.execute("screenshot", {})
    assert res["ok"] is True
    assert isinstance(res["output"], str)
    assert res.get("image_b64"), "screenshot image_b64 missing from execute() result"

    recorded: list[list[dict]] = []

    async def chat(messages, *, model=None, tools=None, temperature=None, max_tokens=None):
        recorded.append([dict(m) for m in messages])
        if len(recorded) == 1:
            return LLMResponse(
                content=None,
                model="m",
                tool_calls=[ToolCall("c1", "screenshot", "{}")],
                finish_reason="tool_calls",
                usage=Usage(1, 1),
            )
        return LLMResponse(
            content="Widze ekran.", model="m", finish_reason="stop", usage=Usage(1, 1)
        )

    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        admin_api_key="adm",
        operator_worker_token=WTOK,
        memory_embedder="hash",
        memory_reflect=False,
        sandbox_backend="local",
    )
    env = {"OLLAMA_URL": "http://localhost"}
    registry = ModelRegistry(load_config(settings.models_config, env), env=env)
    registry.chat = chat
    app = create_app(settings, llm=registry)

    wh = {"Authorization": f"Bearer {WTOK}"}
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as ac,
    ):
        await app.state.operator.poll(wait_s=0.01)  # mark the worker online
        run_task = asyncio.create_task(
            app.state.runner.run(
                "operator", [{"role": "user", "content": "spojrz na ekran"}], client="console"
            )
        )
        cmd = None
        for _ in range(200):
            r = await ac.post("/v1/operator/poll", headers=wh)
            cmd = r.json()["command"]
            if cmd:
                break
            await asyncio.sleep(0.01)
        assert cmd and cmd["action"] == "screenshot"

        result = worker.execute(cmd["action"], cmd.get("params", {}))
        assert "image_b64" in result
        # 2) the real /result endpoint must accept image_b64 (no 422).
        rr = await ac.post("/v1/operator/result", json={"id": cmd["id"], **result}, headers=wh)
        assert rr.status_code == 200, rr.text
        assert rr.json()["accepted"] is True

        agent_result = await asyncio.wait_for(run_task, 5)

    # 3) the screenshot image reached the model on the next call as an image_url block.
    assert agent_result.content == "Widze ekran."
    assert len(recorded) >= 2
    assert _has_image(recorded[1]), "image_url not fed to the model on the follow-up call"
