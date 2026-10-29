"""Approval gate: risky tool calls wait for the owner's YES/NO; timeout means NO."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.approvals.risk import classify

log = logging.getLogger(__name__)

NotifyFn = Callable[[dict[str, Any]], Awaitable[None]]

_YES = {"tak", "t", "yes", "y", "ok", "ja", "true", "1"}
_NO = {"nie", "n", "no", "nein", "false", "0"}


def parse_answer(text: str) -> bool | None:
    word = text.strip().lower().rstrip("!.")
    return True if word in _YES else False if word in _NO else None


@dataclass
class Pending:
    id: str
    client: str
    tool: str
    arguments: str
    reason: str
    created_at: float
    future: asyncio.Future[bool] = field(repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "client": self.client,
            "tool": self.tool,
            "arguments": self.arguments,
            "reason": self.reason,
            "created_at": self.created_at,
        }


class ApprovalGate:
    def __init__(
        self,
        timeout_s: float = 600.0,
        notify: NotifyFn | None = None,
        mode: Literal["risky", "off"] = "risky",
    ) -> None:
        self.timeout_s = timeout_s
        self.notify = notify
        self.mode = mode
        self._pending: dict[str, Pending] = {}

    async def review(self, tool: str, args: dict[str, Any], client: str) -> str | None:
        if self.mode == "off":
            return None
        reason = classify(tool, args)
        if reason is None:
            return None
        pending = Pending(
            id=uuid.uuid4().hex[:12],
            client=client,
            tool=tool,
            arguments=json.dumps(args, ensure_ascii=False)[:2000],
            reason=reason,
            created_at=time.time(),
            future=asyncio.get_running_loop().create_future(),
        )
        self._pending[pending.id] = pending
        log.info("approval %s requested: %s (%s)", pending.id, tool, reason)
        try:
            if self.notify is not None:
                try:
                    await self.notify(pending.public())
                except Exception:
                    log.exception("approval notification failed")
            try:
                approved = await asyncio.wait_for(asyncio.shield(pending.future), self.timeout_s)
            except TimeoutError:
                log.info("approval %s timed out -> denied", pending.id)
                return f"no answer from the owner within {int(self.timeout_s)}s ({reason})"
        finally:
            self._pending.pop(pending.id, None)
        log.info("approval %s %s", pending.id, "granted" if approved else "rejected")
        return None if approved else f"the owner rejected this action ({reason})"

    def pending(self) -> list[dict[str, Any]]:
        return [p.public() for p in self._pending.values()]

    def resolve(self, approval_id: str, approved: bool) -> bool:
        pending = self._pending.get(approval_id)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(approved)
        return True
