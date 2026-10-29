"""Classify tool calls that need the owner's explicit approval."""

import re
import shlex
from typing import Any

_SHELL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s"), "deletes files"),
    (re.compile(r"\bgit\s+push\b"), "git push"),
    (re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-\w*f)"), "destructive git operation"),
    (re.compile(r"\b(mkfs|dd\s+if=|shutdown|reboot)\b"), "system-level destructive command"),
    (
        re.compile(
            r"\b(deploy|rsync|scp|ssh|kubectl|terraform|helm|vercel|netlify|"
            r"docker\s+(push|run)|npm\s+publish|twine\s+upload|firebase\s+deploy)\b"
        ),
        "deployment / remote action",
    ),
    (re.compile(r"\b(stripe|paypal|checkout|purchase|invoice)\b", re.I), "possible spending"),
]

_GIT_RULES: dict[str, str] = {
    "push": "git push",
    "reset": "git reset",
    "clean": "git clean (deletes untracked files)",
    "rm": "git rm (deletes files)",
}


# Operator actions on the owner's own computer that should be confirmed from the phone.
_OPERATOR_RISKY = {
    "os_shell": "runs a shell command on your computer",
    "os_run": "launches a program on your computer",
    "os_write_file": "writes a file on your computer",
    "os_delete": "deletes files on your computer",
    "email_send": "sends an email",
    "calendar_delete": "deletes a calendar event",
    "invoice_create": "issues an invoice",
}


def classify(tool: str, args: dict[str, Any]) -> str | None:
    """Return a short reason if the call is risky, else None."""
    if tool in _OPERATOR_RISKY:
        return _OPERATOR_RISKY[tool]
    if tool == "shell":
        command = str(args.get("command", ""))
        for pattern, reason in _SHELL_RULES:
            if pattern.search(command):
                return reason
    elif tool == "git":
        raw = args.get("args") or []
        argv = shlex.split(raw) if isinstance(raw, str) else [str(a) for a in raw]
        if argv and argv[0] == "git":
            argv = argv[1:]
        sub = next((a for a in argv if not a.startswith("-")), "")
        if sub in _GIT_RULES:
            return _GIT_RULES[sub]
        if sub == "branch" and any(a in {"-D", "-d", "--delete"} for a in argv):
            return "deletes a git branch"
    return None
