"""Asyncio worker that executes queued tasks with retry and cancellation."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from app.tasks.store import CANCELLED, Task, TaskStore

log = logging.getLogger(__name__)

TaskRunner = Callable[[Task], Awaitable[str]]
Notifier = Callable[[Task], Awaitable[None]]


class Worker:
    def __init__(
        self,
        store: TaskStore,
        runner: TaskRunner,
        notifier: Notifier | None = None,
        concurrency: int = 1,
        poll_interval: float = 1.0,
        retry_backoff: float = 5.0,
    ) -> None:
        self.store = store
        self.runner = runner
        self.notifier = notifier
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.retry_backoff = retry_backoff
        self._wake = asyncio.Event()
        self._loops: list[asyncio.Task[None]] = []
        self._running: dict[str, asyncio.Task[str]] = {}
        self._stopping = False

    def start(self) -> None:
        recovered = self.store.recover()
        if recovered:
            log.info("recovered %d interrupted tasks", recovered)
        self._loops = [asyncio.create_task(self._loop()) for _ in range(self.concurrency)]

    async def stop(self) -> None:
        self._stopping = True
        for t in self._loops:
            t.cancel()
        for t in self._loops:
            with contextlib.suppress(asyncio.CancelledError):
                await t

    def wake(self) -> None:
        self._wake.set()

    async def cancel(self, task_id: str) -> bool:
        cancelled = await asyncio.to_thread(self.store.cancel, task_id)
        running = self._running.get(task_id)
        if cancelled and running is not None:
            running.cancel()
        return cancelled

    async def _loop(self) -> None:
        while True:
            task = await asyncio.to_thread(self.store.claim_next)
            if task is None:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self.poll_interval)
                continue
            await self._execute(task)

    async def _execute(self, task: Task) -> None:
        log.info("task %s start agent=%s attempt=%d", task.id, task.agent, task.attempts)
        job = asyncio.create_task(self.runner(task))
        self._running[task.id] = job
        try:
            result = await job
        except asyncio.CancelledError:
            if self._stopping:
                job.cancel()
                await asyncio.to_thread(self.store.requeue, task.id)
                raise
            log.info("task %s cancelled", task.id)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:2000]
            if task.attempts < task.max_attempts:
                delay = self.retry_backoff * 2 ** (task.attempts - 1)
                log.warning("task %s failed (%s), retry in %.0fs", task.id, error[:200], delay)
                await asyncio.to_thread(self.store.fail, task.id, error, delay)
                return
            log.warning("task %s failed permanently: %s", task.id, error[:200])
            await asyncio.to_thread(self.store.fail, task.id, error)
        else:
            await asyncio.to_thread(self.store.complete, task.id, result)
            log.info("task %s done", task.id)
        finally:
            self._running.pop(task.id, None)
        await self._notify(task.id)

    async def _notify(self, task_id: str) -> None:
        if self.notifier is None:
            return
        final = await asyncio.to_thread(self.store.get, task_id)
        if final is None or (final.status == CANCELLED and not final.webhook_url):
            return
        try:
            await self.notifier(final)
        except Exception:
            log.exception("notifier failed for task %s", task_id)
