import json
from pathlib import Path

import pytest

from app.agent.loop import AgentRunner, parse_text_tool_calls, safe_name
from app.agents.profiles import AgentRegistry
from app.llm.mock import MockLLM, tool_reply
from app.llm.types import LLMResponse, ToolCall
from app.sandbox.runner import ExecResult

AGENTS = """
agents:
  boss:
    model: m
    system_prompt: You lead.
    tools: [delegate]
    delegates: [coder]
    max_steps: 4
  coder:
    model: m
    system_prompt: You code.
    tools: [write_file, read_file, shell]
    max_steps: 3
  texty:
    model: m
    system_prompt: Old model.
    tools: [read_file]
    native_tools: false
"""


class FakeSandbox:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def run(self, command, workspace, timeout_s=None, network=False) -> ExecResult:
        self.commands.append(command)
        return ExecResult(0, "2 passed")


@pytest.fixture
def agents(tmp_path: Path) -> AgentRegistry:
    p = tmp_path / "agents.yaml"
    p.write_text(AGENTS)
    return AgentRegistry(p, ["m"])


def runner(llm: MockLLM, agents: AgentRegistry, tmp_path: Path, **kw) -> AgentRunner:
    return AgentRunner(llm, agents, FakeSandbox(), tmp_path / "ws", **kw)


USER = [{"role": "user", "content": "build it"}]


async def test_tool_loop(agents: AgentRegistry, tmp_path: Path) -> None:
    llm = MockLLM(
        [
            tool_reply("write_file", json.dumps({"path": "a.py", "content": "x=1"}), "c1"),
            tool_reply("shell", json.dumps({"command": "pytest"}), "c2"),
            "Done: wrote a.py, tests pass.",
        ]
    )
    r = runner(llm, agents, tmp_path)
    result = await r.run("coder", USER, client="app 1")
    assert result.content == "Done: wrote a.py, tests pass."
    assert result.steps == 3 and result.stopped == "final"
    assert (tmp_path / "ws" / "app_1" / "a.py").read_text() == "x=1"
    assert [t["tool"] for t in result.tool_log] == ["write_file", "shell"]
    last = llm.calls[-1]["messages"]
    assert last[0]["role"] == "system" and "You code." in last[0]["content"]
    assert last[-1] == {"role": "tool", "tool_call_id": "c2", "content": "exit_code=0\n2 passed"}
    assert llm.calls[0]["tools"][0]["function"]["name"] == "write_file"


async def test_tool_errors_are_fed_back(agents: AgentRegistry, tmp_path: Path) -> None:
    llm = MockLLM(
        [
            tool_reply("read_file", '{"path": "../../etc/passwd"}', "c1"),
            tool_reply("nope", "{}", "c2"),
            "gave up",
        ]
    )
    result = await runner(llm, agents, tmp_path).run("coder", USER)
    msgs = llm.calls[-1]["messages"]
    assert msgs[-3]["content"].startswith("ERROR: path escapes")
    assert msgs[-1]["content"].startswith("ERROR: unknown tool")
    assert result.tool_log[0]["ok"] is False


async def test_bad_json_arguments(agents: AgentRegistry, tmp_path: Path) -> None:
    llm = MockLLM([tool_reply("read_file", "{not json", "c1"), "ok"])
    await runner(llm, agents, tmp_path).run("coder", USER)
    assert "invalid JSON" in llm.calls[-1]["messages"][-1]["content"]


async def test_step_limit_forces_summary(agents: AgentRegistry, tmp_path: Path) -> None:
    def respond(messages):
        if messages[-1]["content"].startswith("Step limit"):
            return LLMResponse(content="summary", model="m")
        return tool_reply("shell", '{"command": "ls"}')

    llm = MockLLM([respond])
    result = await runner(llm, agents, tmp_path).run("coder", USER)
    assert result.stopped == "max_steps" and result.content == "summary"
    assert llm.calls[-1]["tools"] is None
    assert len(llm.calls) == 4  # 3 steps + summary


async def test_delegation(agents: AgentRegistry, tmp_path: Path) -> None:
    def respond(messages):
        system = messages[0]["content"]
        if "You lead." in system:
            if messages[-1]["role"] == "tool":
                return LLMResponse(content="Boss: " + messages[-1]["content"], model="m")
            return tool_reply("delegate", json.dumps({"agent": "coder", "task": "write x"}))
        return LLMResponse(content="coder finished " + messages[-1]["content"], model="m")

    result = await runner(MockLLM([respond]), agents, tmp_path).run("boss", USER)
    assert result.content == "Boss: coder finished write x"


async def test_delegation_depth_limit(agents: AgentRegistry, tmp_path: Path) -> None:
    llm = MockLLM([tool_reply("delegate", '{"agent": "coder", "task": "x"}'), "end"])
    r = runner(llm, agents, tmp_path, max_depth=0)
    await r.run("boss", USER)
    assert "cannot delegate" in llm.calls[1]["messages"][-1]["content"]


async def test_text_tool_protocol(agents: AgentRegistry, tmp_path: Path) -> None:
    ws = tmp_path / "ws" / "default"
    ws.mkdir(parents=True)
    (ws / "n.txt").write_text("hello")
    llm = MockLLM(
        [
            'Reading.\n```tool\n{"name": "read_file", "arguments": {"path": "n.txt"}}\n```',
            "It says hello.",
        ]
    )
    result = await runner(llm, agents, tmp_path).run("texty", USER)
    assert result.content == "It says hello."
    first = llm.calls[0]
    assert first["tools"] is None and "```tool" in first["messages"][0]["content"]
    assert llm.calls[1]["messages"][-1] == {
        "role": "user",
        "content": "Result of read_file:\n1| hello",
    }


async def test_approver_denial(agents: AgentRegistry, tmp_path: Path) -> None:
    class Deny:
        async def review(self, tool, args, client):
            return "owner said no" if tool == "shell" else None

    llm = MockLLM([tool_reply("shell", '{"command": "rm -rf x"}'), "ok"])
    r = runner(llm, agents, tmp_path, approver=Deny())
    await r.run("coder", USER)
    assert llm.calls[1]["messages"][-1]["content"].startswith("DENIED: owner said no")
    assert r.sandbox.commands == []


async def test_memory_hooks(agents: AgentRegistry, tmp_path: Path) -> None:
    class Mem:
        recorded = None

        async def context(self, agent, query):
            return f"## Lessons\n- remember {query}"

        async def record(self, agent, client, messages, answer):
            Mem.recorded = (agent, client, answer)
            return 42

    llm = MockLLM(["answer"])
    result = await runner(llm, agents, tmp_path, memory=Mem()).run("coder", USER, client="c")
    assert "remember build it" in llm.calls[0]["messages"][0]["content"]
    assert Mem.recorded == ("coder", "c", "answer") and result.interaction_id == 42


async def test_unknown_agent(agents: AgentRegistry, tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        await runner(MockLLM(), agents, tmp_path).run("ghost", USER)


def test_parse_text_tool_calls() -> None:
    calls = parse_text_tool_calls('```tool\n{"name": "a", "arguments": {"x": 1}}\n```')
    assert calls[0].name == "a" and json.loads(calls[0].arguments) == {"x": 1}
    assert parse_text_tool_calls('{"name": "b"}')[0].name == "b"
    assert parse_text_tool_calls("plain answer") == []
    assert parse_text_tool_calls("```tool\n{broken\n```") == []
    assert isinstance(parse_text_tool_calls('{"name":"c"}')[0], ToolCall)


def test_safe_name() -> None:
    assert safe_name("../evil") == ".._evil"
    assert safe_name("") == "default"


async def test_services_passed_to_tools(agents: AgentRegistry, tmp_path: Path) -> None:
    from app.llm.mock import tool_reply

    (tmp_path / "agents2.yaml").write_text(
        "agents:\n  mailer: {model: m, system_prompt: You mail., tools: [email_list]}\n"
    )
    reg = AgentRegistry(tmp_path / "agents2.yaml", ["m"])

    class FakeMB:
        def list_sync(self, folder, limit):
            return []

    llm = MockLLM([tool_reply("email_list", "{}", "c1"), "no mail"])
    r = AgentRunner(llm, reg, FakeSandbox(), tmp_path / "ws", services={"mailbox": FakeMB()})
    result = await r.run("mailer", [{"role": "user", "content": "check mail"}])
    assert result.content == "no mail"
    assert "(no messages)" in llm.calls[-1]["messages"][-1]["content"]


async def test_screenshot_image_fed_to_model(agents: AgentRegistry, tmp_path: Path) -> None:
    from app.llm.mock import tool_reply
    from app.operator.hub import OperatorHub

    (tmp_path / "op.yaml").write_text(
        "agents:\n  op: {model: m, system_prompt: You see., tools: [screenshot]}\n"
    )
    reg = AgentRegistry(tmp_path / "op.yaml", ["m"])
    hub = OperatorHub()
    await hub.poll(wait_s=0.01)

    import asyncio

    async def worker() -> None:
        cmd = await hub.poll(wait_s=1)
        hub.submit_result(cmd["id"], {"ok": True, "output": "screen 100x100", "image_b64": "QUJD"})

    llm = MockLLM([tool_reply("screenshot", "{}", "c1"), "I can see the desktop."])
    runner = AgentRunner(llm, reg, FakeSandbox(), tmp_path / "ws", operator_hub=hub)
    task = asyncio.create_task(worker())
    result = await runner.run("op", [{"role": "user", "content": "look"}])
    await task
    assert result.content == "I can see the desktop."
    # the second LLM call must include an image_url content block
    last_msgs = llm.calls[-1]["messages"]
    image_msg = next(m for m in last_msgs if isinstance(m.get("content"), list))
    blocks = image_msg["content"]
    assert any(b.get("type") == "image_url" for b in blocks)
    assert blocks[-1]["image_url"]["url"] == "data:image/png;base64,QUJD"
