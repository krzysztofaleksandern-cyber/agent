import asyncio

import pytest

from app.agents.profiles import AgentRegistry
from app.approvals.risk import classify
from app.operator.hub import OperatorHub, WorkerOffline
from app.operator.tools import OPERATOR_TOOLS, RISKY_ACTIONS
from app.tools.base import ToolContext, ToolError


async def _drive_worker(hub: OperatorHub, reply: dict, wait: float = 1.0) -> None:
    """Act as the host worker: pull one command and answer it."""
    cmd = await hub.poll(wait_s=wait)
    assert cmd is not None
    hub.submit_result(cmd["id"], reply)


async def test_dispatch_roundtrip() -> None:
    hub = OperatorHub()
    await hub.poll(wait_s=0.01)  # marks the worker online
    worker = asyncio.create_task(_drive_worker(hub, {"ok": True, "output": "clicked"}))
    out = await hub.dispatch("mouse_click", {"x": 10, "y": 20})
    await worker
    assert out == {"ok": True, "output": "clicked"}


async def test_offline_when_never_polled() -> None:
    hub = OperatorHub()
    assert not hub.online
    with pytest.raises(WorkerOffline):
        await hub.dispatch("screenshot", {})


async def test_dispatch_timeout() -> None:
    hub = OperatorHub(dispatch_timeout=0.05)
    await hub.poll(wait_s=0.01)
    with pytest.raises(WorkerOffline, match="did not answer"):
        await hub.dispatch("os_shell", {"command": "x"})


async def test_poll_returns_none_after_wait() -> None:
    hub = OperatorHub()
    assert await hub.poll(wait_s=0.01) is None


def test_submit_unknown_result() -> None:
    assert OperatorHub().submit_result("nope", {"ok": True}) is False


async def test_operator_tool_calls_hub() -> None:
    hub = OperatorHub()
    await hub.poll(wait_s=0.01)
    ctx = ToolContext(workspace=None, sandbox=None, operator_hub=hub)  # type: ignore[arg-type]
    worker = asyncio.create_task(_drive_worker(hub, {"ok": True, "output": "typed 3 chars"}))
    out = await OPERATOR_TOOLS["type_text"].handler({"text": "abc"}, ctx)
    await worker
    assert out == "typed 3 chars"


async def test_operator_tool_error_surfaces() -> None:
    hub = OperatorHub()
    await hub.poll(wait_s=0.01)
    ctx = ToolContext(workspace=None, sandbox=None, operator_hub=hub)  # type: ignore[arg-type]
    worker = asyncio.create_task(_drive_worker(hub, {"ok": False, "error": "file not found"}))
    with pytest.raises(ToolError, match="file not found"):
        await OPERATOR_TOOLS["os_read_file"].handler({"path": "x"}, ctx)
    await worker


async def test_operator_tool_offline() -> None:
    ctx = ToolContext(workspace=None, sandbox=None, operator_hub=OperatorHub())  # type: ignore[arg-type]
    with pytest.raises(ToolError, match="not reachable"):
        await OPERATOR_TOOLS["screenshot"].handler({}, ctx)


def test_operator_actions_classified_risky() -> None:
    assert classify("os_shell", {"command": "Remove-Item x"}) is not None
    assert classify("os_run", {"target": "notepad.exe"}) is not None
    assert classify("os_write_file", {"path": "c:/x", "content": "y"}) is not None
    # benign desktop actions are not individually gated
    assert classify("mouse_click", {"x": 1, "y": 2}) is None
    assert classify("screenshot", {}) is None
    assert {"os_shell", "os_run", "os_write_file", "os_delete"} == RISKY_ACTIONS


def test_operator_agent_profile_valid() -> None:
    from pathlib import Path

    from app.llm.registry import load_config

    root = Path(__file__).parent.parent
    aliases = load_config(root / "config/models.yaml", {"OLLAMA_URL": "x", "GEMINI_API_KEYS": "k"})
    reg = AgentRegistry(root / "config/agents.yaml", aliases.models)
    op = reg.get("operator")
    assert op is not None and "screenshot" in op.tools and "os_shell" in op.tools
