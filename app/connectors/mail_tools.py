"""Agent tools for email, backed by a Mailbox in ToolContext.services['mailbox']."""

import asyncio
from typing import Any

from app.connectors.email import MailError
from app.tools.base import Tool, ToolContext, ToolError

MAX_BODY = 8000


def _mailbox(ctx: ToolContext) -> Any:
    mb = ctx.services.get("mailbox")
    if mb is None:
        raise ToolError("email is not configured (set EMAIL_* in .env)")
    return mb


async def email_list(args: dict[str, Any], ctx: ToolContext) -> str:
    mb = _mailbox(ctx)
    folder = str(args.get("folder") or "INBOX")
    limit = min(int(args.get("limit") or 20), 50)
    try:
        items = await asyncio.to_thread(mb.list_sync, folder, limit)
    except MailError as exc:
        raise ToolError(str(exc)) from exc
    if not items:
        return "(no messages)"
    return "\n".join(f"[{m.uid}] {m.date} — {m.from_addr} — {m.subject}" for m in items)


async def email_read(args: dict[str, Any], ctx: ToolContext) -> str:
    mb = _mailbox(ctx)
    uid = str(args.get("uid") or "")
    if not uid:
        raise ToolError("argument 'uid' is required")
    try:
        m = await asyncio.to_thread(mb.read_sync, uid, str(args.get("folder") or "INBOX"))
    except MailError as exc:
        raise ToolError(str(exc)) from exc
    body = m.body[:MAX_BODY] + ("\n…[truncated]" if len(m.body) > MAX_BODY else "")
    return f"From: {m.from_addr}\nTo: {m.to}\nDate: {m.date}\nSubject: {m.subject}\n\n{body}"


async def email_send(args: dict[str, Any], ctx: ToolContext) -> str:
    mb = _mailbox(ctx)
    to = str(args.get("to") or "")
    subject = str(args.get("subject") or "")
    body = str(args.get("body") or "")
    if not to or not subject:
        raise ToolError("arguments 'to' and 'subject' are required")
    try:
        return await asyncio.to_thread(mb.send_sync, to, subject, body, str(args.get("cc") or ""))
    except MailError as exc:
        raise ToolError(str(exc)) from exc


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


MAIL_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "email_list",
            "List recent emails in a folder (default INBOX). Returns uid, date, sender, subject.",
            _obj({"folder": {"type": "string"}, "limit": {"type": "integer"}}, []),
            email_list,
        ),
        Tool(
            "email_read",
            "Read one email by its uid (from email_list).",
            _obj({"uid": {"type": "string"}, "folder": {"type": "string"}}, ["uid"]),
            email_read,
        ),
        Tool(
            "email_send",
            "Send an email. Requires the owner's approval.",
            _obj(
                {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string"},
                },
                ["to", "subject", "body"],
            ),
            email_send,
        ),
    ]
}
