"""Logging setup and helpers that keep secrets and message bodies out of logs."""

import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
    re.compile(r"\b(sk-|gsk_|EAA)[A-Za-z0-9_\-]{8,}"),
]


def redact(text: str) -> str:
    """Mask anything that looks like a credential."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "***", text)
    return text


def preview(text: str, limit: int = 40) -> str:
    """Short, redacted preview of a message body, safe to log."""
    flat = redact(" ".join(text.split()))
    if len(flat) <= limit:
        return flat
    return f"{flat[:limit]}… ({len(text)} chars)"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            '{"ts":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}'
        )
    )
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
