from pathlib import Path

from app.agents.profiles import AgentRegistry
from app.audit.log import AuditLog
from app.llm.mock import MockLLM, tool_reply
from app.sandbox.runner import ExecResult


def test_audit_record_and_query(tmp_path: Path) -> None:
    a = AuditLog(tmp_path / "a.db")
    a.record("operator", "console", "os_shell", "ls", True)
    a.record("operator", "console", "os_shell", "rm x", False, "DENIED")
    a.record("codex", "bot", "shell", "pytest", True)
    recent = a.recent()
    assert len(recent) == 3 and recent[0].tool == "shell"  # newest first
    assert [e.ok for e in a.recent(agent="operator")] == [False, True]
    denied = next(e for e in recent if not e.ok)
    assert denied.note == "DENIED"


class FakeSandbox:
    async def run(self, command, workspace, timeout_s=None, network=False) -> ExecResult:
        return ExecResult(0, "ok")


async def test_agent_loop_writes_audit(tmp_path: Path) -> None:
    from app.agent.loop import AgentRunner

    (tmp_path / "ag.yaml").write_text(
        "agents:\n  c: {model: m, system_prompt: hi, tools: [shell]}\n"
    )
    reg = AgentRegistry(tmp_path / "ag.yaml", ["m"])
    audit = AuditLog(tmp_path / "a.db")
    llm = MockLLM([tool_reply("shell", '{"command": "ls"}', "c1"), "done"])
    runner = AgentRunner(llm, reg, FakeSandbox(), tmp_path / "ws", audit=audit)
    await runner.run("c", [{"role": "user", "content": "go"}], client="bot")
    entries = audit.recent()
    assert len(entries) == 1
    assert entries[0].tool == "shell" and entries[0].agent == "c" and entries[0].client == "bot"
    assert entries[0].ok is True
