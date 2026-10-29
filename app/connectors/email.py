"""Email connector: read, draft and send mail via IMAP/SMTP (standard library only)."""

import email
import imaplib
import smtplib
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Protocol


class MailError(Exception):
    """Mailbox operation failed."""


@dataclass(frozen=True)
class MailSummary:
    uid: str
    from_addr: str
    subject: str
    date: str


@dataclass(frozen=True)
class MailMessage:
    uid: str
    from_addr: str
    to: str
    subject: str
    date: str
    body: str


class Mailbox(Protocol):
    async def list(self, folder: str = "INBOX", limit: int = 20) -> list[MailSummary]: ...
    async def read(self, uid: str, folder: str = "INBOX") -> MailMessage: ...
    async def send(self, to: str, subject: str, body: str, cc: str = "") -> str: ...


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _body_of(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""


@dataclass
class EmailConfig:
    imap_host: str
    smtp_host: str
    username: str
    password: str
    from_addr: str
    imap_port: int = 993
    smtp_port: int = 587


class ImapSmtpMailbox:
    """Blocking IMAP/SMTP client; call its methods via asyncio.to_thread (see the tools)."""

    def __init__(self, config: EmailConfig) -> None:
        self.cfg = config

    def list_sync(self, folder: str, limit: int) -> list[MailSummary]:
        try:
            with imaplib.IMAP4_SSL(self.cfg.imap_host, self.cfg.imap_port) as im:
                im.login(self.cfg.username, self.cfg.password)
                im.select(folder, readonly=True)
                _, data = im.uid("search", None, "ALL")
                uids = (data[0] or b"").split()[-limit:][::-1]
                out: list[MailSummary] = []
                for uid in uids:
                    _, msg_data = im.uid("fetch", uid, "(BODY.PEEK[HEADER])")
                    if not msg_data or not isinstance(msg_data[0], tuple):
                        continue
                    hdr = email.message_from_bytes(msg_data[0][1])
                    out.append(
                        MailSummary(
                            uid.decode(),
                            parseaddr(_decode(hdr.get("From")))[1],
                            _decode(hdr.get("Subject")),
                            _decode(hdr.get("Date")),
                        )
                    )
                return out
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(f"IMAP error: {type(exc).__name__}") from exc

    def read_sync(self, uid: str, folder: str) -> MailMessage:
        try:
            with imaplib.IMAP4_SSL(self.cfg.imap_host, self.cfg.imap_port) as im:
                im.login(self.cfg.username, self.cfg.password)
                im.select(folder, readonly=True)
                _, msg_data = im.uid("fetch", uid.encode(), "(RFC822)")
                if not msg_data or not isinstance(msg_data[0], tuple):
                    raise MailError(f"message {uid} not found")
                msg = email.message_from_bytes(msg_data[0][1])
                return MailMessage(
                    uid,
                    parseaddr(_decode(msg.get("From")))[1],
                    _decode(msg.get("To")),
                    _decode(msg.get("Subject")),
                    _decode(msg.get("Date")),
                    _body_of(msg),
                )
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(f"IMAP error: {type(exc).__name__}") from exc

    def send_sync(self, to: str, subject: str, body: str, cc: str = "") -> str:
        msg = EmailMessage()
        msg["From"] = self.cfg.from_addr
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        msg.set_content(body)
        recipients = [a for a in [to, cc] if a]
        try:
            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.cfg.username, self.cfg.password)
                smtp.send_message(msg, to_addrs=recipients)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"SMTP error: {type(exc).__name__}") from exc
        return f"sent to {to}"
