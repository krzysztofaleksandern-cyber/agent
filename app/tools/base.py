"""Tool abstraction shared by all agent tools."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.sandbox.runner import SandboxRunner

ApproveFn = Callable[[str, str], Awaitable[bool]]  # (action, details) -> approved?
DelegateFn = Callable[[str, str], Awaitable[str]]  # (agent, task) -> result


class ToolError(Exception):
    """Expected tool failure; the message is shown to the model."""


@dataclass
class ToolContext:
    workspace: Path
    sandbox: SandboxRunner
    client: str = ""
    http_allowlist: list[str] = field(default_factory=list)
    http: httpx.AsyncClient | None = None
    approve: ApproveFn | None = None
    delegate: DelegateFn | None = None
    delegates: list[str] = field(default_factory=list)
    operator_hub: Any = None  # OperatorHub, set for the operator agent only
    services: dict[str, Any] = field(default_factory=dict)  # named connectors (mailbox, …)
    images: list[str] = field(default_factory=list)  # data URLs a tool wants the model to see


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def jail(workspace: Path, path: str) -> Path:
    """Resolve `path` inside the workspace; reject escapes (.., absolute paths, symlinks)."""
    root = workspace.resolve()
    rel = re.sub(r"^/workspace/?", "", path.strip()) or "."
    if rel.startswith("/"):
        raise ToolError(f"absolute paths outside /workspace are not allowed: {path}")
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"path escapes /workspace: {path}")
    return target
