from pathlib import Path

from app.agent.loop import AgentRunner
from app.agents.profiles import AgentRegistry
from app.control import ControlState
from app.llm.mock import MockLLM, tool_reply
from app.sandbox.runner import ExecResult


class FakeSandbox:
    def __init__(self) -> None:
        self.ran = 0

    async def run(self, command, workspace, timeout_s=None, network=False) -> ExecResult:
        self.ran += 1
        return ExecResult(0, "ok")


def test_control_state() -> None:
    c = ControlState()
    assert not c.paused
    assert c.set_paused(True) is True and c.paused
    c.set_paused(False)
    assert not c.paused


async def test_paused_runner_takes_no_action(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "agents:\n  c: {model: m, system_prompt: hi, tools: [shell]}\n"
    )
    reg = AgentRegistry(tmp_path / "a.yaml", ["m"])
    sandbox = FakeSandbox()
    control = ControlState(paused=True)
    llm = MockLLM([tool_reply("shell", '{"command": "ls"}', "c1"), "done"])
    runner = AgentRunner(llm, reg, sandbox, tmp_path / "ws", control=control)
    result = await runner.run("c", [{"role": "user", "content": "go"}])
    assert result.stopped == "paused" and sandbox.ran == 0
    assert "Paused by the owner" in result.content


async def test_resumed_runner_acts(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "agents:\n  c: {model: m, system_prompt: hi, tools: [shell]}\n"
    )
    reg = AgentRegistry(tmp_path / "a.yaml", ["m"])
    sandbox = FakeSandbox()
    control = ControlState(paused=False)
    llm = MockLLM([tool_reply("shell", '{"command": "ls"}', "c1"), "done"])
    runner = AgentRunner(llm, reg, sandbox, tmp_path / "ws", control=control)
    result = await runner.run("c", [{"role": "user", "content": "go"}])
    assert sandbox.ran == 1 and result.content == "done"
