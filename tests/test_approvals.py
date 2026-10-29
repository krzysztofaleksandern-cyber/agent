import asyncio

import pytest

from app.approvals.gate import ApprovalGate, parse_answer
from app.approvals.risk import classify


@pytest.mark.parametrize(
    ("tool", "args", "risky"),
    [
        ("shell", {"command": "pytest -q"}, False),
        ("shell", {"command": "rm -rf build"}, True),
        ("shell", {"command": "git push origin main"}, True),
        ("shell", {"command": "npm run build && vercel --prod"}, True),
        ("shell", {"command": "git reset --hard HEAD~1"}, True),
        ("shell", {"command": "ls -la"}, False),
        ("git", {"args": ["status"]}, False),
        ("git", {"args": ["push", "origin", "main"]}, True),
        ("git", {"args": "git push"}, True),
        ("git", {"args": ["branch", "-D", "old"]}, True),
        ("git", {"args": ["commit", "-m", "x"]}, False),
        ("read_file", {"path": "rm -rf"}, False),
    ],
)
def test_classify(tool: str, args: dict, risky: bool) -> None:
    assert (classify(tool, args) is not None) is risky


def test_parse_answer() -> None:
    assert parse_answer("TAK") is True
    assert parse_answer(" nie! ") is False
    assert parse_answer("ja") is True
    assert parse_answer("maybe") is None


async def test_safe_call_passes_without_asking() -> None:
    gate = ApprovalGate(timeout_s=1)
    assert await gate.review("shell", {"command": "ls"}, "c") is None


async def test_approve_and_reject() -> None:
    sent = []

    async def notify(payload):
        sent.append(payload)

    gate = ApprovalGate(timeout_s=5, notify=notify)
    review = asyncio.create_task(gate.review("git", {"args": ["push"]}, "bot"))
    await asyncio.sleep(0.01)
    assert sent[0]["reason"] == "git push" and gate.pending()[0]["client"] == "bot"
    assert gate.resolve(sent[0]["id"], True)
    assert await review is None
    assert gate.pending() == []
    assert not gate.resolve(sent[0]["id"], True)

    review = asyncio.create_task(gate.review("shell", {"command": "rm x"}, "bot"))
    await asyncio.sleep(0.01)
    gate.resolve(sent[1]["id"], False)
    assert "rejected" in await review


async def test_timeout_is_denial() -> None:
    gate = ApprovalGate(timeout_s=0.05)
    reason = await gate.review("shell", {"command": "rm -rf /workspace/x"}, "c")
    assert "no answer" in reason and gate.pending() == []


async def test_mode_off() -> None:
    assert await ApprovalGate(mode="off").review("git", {"args": ["push"]}, "c") is None
