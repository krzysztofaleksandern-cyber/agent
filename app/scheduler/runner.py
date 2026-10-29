"""Scheduler loop: fires due jobs by handing their prompt to an agent via a callback."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.scheduler.jobs import Job, JobStore

log = logging.getLogger(__name__)

Enqueue = Callable[[Job], Awaitable[None]]


class SchedulerLoop:
    def __init__(self, store: JobStore, enqueue: Enqueue, tick_s: float = 30.0) -> None:
        self.store = store
        self.enqueue = enqueue
        self.tick_s = tick_s
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def tick(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        due = await asyncio.to_thread(self.store.due, now.timestamp())
        for job in due:
            try:
                await self.enqueue(job)
            except Exception:
                log.exception("failed to enqueue job %s", job.id)
            await asyncio.to_thread(self.store.mark_ran, job.id, now)
        return len(due)

    async def _loop(self) -> None:
        while True:
            try:
                fired = await self.tick()
                if fired:
                    log.info("scheduler fired %d job(s)", fired)
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(self.tick_s)
