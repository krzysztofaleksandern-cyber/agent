"""Command channel between the VPS and the host worker running on the owner's computer.

The worker holds no open port: it long-polls the VPS for the next command, runs it locally
(mouse, keyboard, screenshot, shell, files) and posts the result back. The operator agent's
tools call `dispatch()` here and await the worker's reply.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class WorkerOffline(Exception):
    """No host worker has polled recently, or it did not answer in time."""


@dataclass
class Command:
    id: str
    action: str
    params: dict[str, Any]
    created_at: float
    future: asyncio.Future[dict[str, Any]] = field(repr=False)


class OperatorHub:
    def __init__(self, dispatch_timeout: float = 120.0, offline_after: float = 30.0) -> None:
        self.dispatch_timeout = dispatch_timeout
        self.offline_after = offline_after
        self._queue: asyncio.Queue[Command] = asyncio.Queue()
        self._inflight: dict[str, Command] = {}
        self._last_poll: float = 0.0

    @property
    def online(self) -> bool:
        return (time.monotonic() - self._last_poll) < self.offline_after

    async def dispatch(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Enqueue a command for the worker and wait for its result."""
        if not self.online:
            raise WorkerOffline("the computer worker is not connected")
        loop = asyncio.get_running_loop()
        cmd = Command(uuid.uuid4().hex[:12], action, params, time.monotonic(), loop.create_future())
        self._inflight[cmd.id] = cmd
        await self._queue.put(cmd)
        try:
            return await asyncio.wait_for(asyncio.shield(cmd.future), self.dispatch_timeout)
        except TimeoutError as exc:
            raise WorkerOffline(
                f"worker did not answer within {int(self.dispatch_timeout)}s"
            ) from exc
        finally:
            self._inflight.pop(cmd.id, None)

    async def poll(self, wait_s: float = 25.0) -> dict[str, Any] | None:
        """Called by the worker. Returns the next command, or None after `wait_s`."""
        self._last_poll = time.monotonic()
        try:
            cmd = await asyncio.wait_for(self._queue.get(), wait_s)
        except TimeoutError:
            return None
        return {"id": cmd.id, "action": cmd.action, "params": cmd.params}

    def submit_result(self, command_id: str, result: dict[str, Any]) -> bool:
        """Called by the worker with the outcome of a command."""
        self._last_poll = time.monotonic()
        cmd = self._inflight.get(command_id)
        if cmd is None or cmd.future.done():
            return False
        cmd.future.set_result(result)
        return True

    def status(self) -> dict[str, Any]:
        last = time.monotonic() - self._last_poll if self._last_poll else None
        return {
            "online": self.online,
            "seconds_since_poll": round(last, 1) if last is not None else None,
            "inflight": len(self._inflight),
        }
