from pathlib import Path

import pytest

from app.agents.profiles import AgentRegistry
from app.connectors.email import MailError, MailMessage, MailSummary
from app.connectors.mail_tools import MAIL_TOOLS
from app.llm.registry import load_config
from app.tools.base import ToolContext, ToolError

ROOT = Path(__file__).parent.parent


class FakeMailbox:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.fail = False

    def list_sync(self, folder: str, limit: int) -> list[MailSummary]:
        if self.fail:
            raise MailError("IMAP error: boom")
        return [MailSummary("5", "a@x.com", "Hi", "Mon"), MailSummary("4", "b@x.com", "Re", "Sun")][
            :limit
        ]

    def read_sync(self, uid: str, folder: str) -> MailMessage:
        if uid != "5":
            raise MailError("message not found")
        return MailMessage("5", "a@x.com", "me@x.com", "Hi", "Mon", "Hello there")

    def send_sync(self, to: str, subject: str, body: str, cc: str = "") -> str:
        self.sent.append((to, subject, body, cc))
        return f"sent to {to}"


def ctx_with(mb: FakeMailbox | None) -> ToolContext:
    return ToolContext(workspace=None, sandbox=None, services={"mailbox": mb} if mb else {})  # type: ignore[arg-type]


async def test_email_list_and_read() -> None:
    ctx = ctx_with(FakeMailbox())
    out = await MAIL_TOOLS["email_list"].handler({"limit": 1}, ctx)
    assert "[5]" in out and "a@x.com" in out
    read = await MAIL_TOOLS["email_read"].handler({"uid": "5"}, ctx)
    assert "Hello there" in read and "Subject: Hi" in read
    with pytest.raises(ToolError, match="not found"):
        await MAIL_TOOLS["email_read"].handler({"uid": "99"}, ctx)


async def test_email_send() -> None:
    mb = FakeMailbox()
    out = await MAIL_TOOLS["email_send"].handler(
        {"to": "c@x.com", "subject": "Hej", "body": "treść"}, ctx_with(mb)
    )
    assert out == "sent to c@x.com" and mb.sent[0][0] == "c@x.com"
    with pytest.raises(ToolError, match="required"):
        await MAIL_TOOLS["email_send"].handler({"to": "c@x.com"}, ctx_with(mb))


async def test_email_not_configured() -> None:
    with pytest.raises(ToolError, match="not configured"):
        await MAIL_TOOLS["email_list"].handler({}, ctx_with(None))


async def test_email_error_surfaces() -> None:
    mb = FakeMailbox()
    mb.fail = True
    with pytest.raises(ToolError, match="IMAP error"):
        await MAIL_TOOLS["email_list"].handler({}, ctx_with(mb))


def test_email_send_is_risky() -> None:
    from app.approvals.risk import classify

    assert classify("email_send", {"to": "x", "subject": "y"}) is not None
    assert classify("email_list", {}) is None


def test_secretary_has_email_tools() -> None:
    aliases = load_config(ROOT / "config/models.yaml", {"OLLAMA_URL": "x", "GEMINI_API_KEYS": "k"})
    reg = AgentRegistry(ROOT / "config/agents.yaml", aliases.models)
    assert "email_send" in reg.get("secretary").tools
