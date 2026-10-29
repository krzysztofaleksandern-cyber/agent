import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.llm.usage import UsageMeter
from app.tasks.store import CANCELLED, DONE, FAILED, QUEUED, RUNNING, Task, TaskStore
from app.tasks.webhook import SIGNATURE_HEADER, WebhookSender, verify
from app.tasks.worker import Worker

MSGS = [{"role": "user", "content": "do it"}]


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "t.db")


async def wait_status(store: TaskStore, task_id: str, status: str, limit_s: float = 3.0) -> Task:
    async with asyncio.timeout(limit_s):
        while True:
            task = store.get(task_id)
            if task and task.status == status:
                return task
            await asyncio.sleep(0.01)


def test_store_lifecycle(store: TaskStore) -> None:
    t = store.create("app", "codex", MSGS)
    assert t.status == QUEUED and t.messages == MSGS
    claimed = store.claim_next()
    assert claimed.id == t.id and claimed.status == RUNNING and claimed.attempts == 1
    assert store.claim_next() is None
    assert store.fail(t.id, "boom", retry_in=0)
    assert store.get(t.id).status == QUEUED
    store.claim_next()
    assert store.complete(t.id, "result")
    done = store.get(t.id)
    assert done.status == DONE and done.result == "result" and done.attempts == 2
    assert not store.cancel(t.id)  # final state


def test_store_recover_and_requeue(store: TaskStore) -> None:
    a = store.create("app", "x", MSGS)
    store.claim_next()
    assert store.recover() == 1
    assert store.get(a.id).status == QUEUED
    store.claim_next()
    assert store.requeue(a.id)
    assert store.get(a.id).attempts == 1
    assert [t.id for t in store.list(client="app")] == [a.id]
    assert store.list(client="other") == []


async def test_worker_runs_and_notifies(store: TaskStore) -> None:
    notified: list[Task] = []

    async def runner(task: Task) -> str:
        return "ok:" + task.messages[0]["content"]

    async def notify(task: Task) -> None:
        notified.append(task)

    worker = Worker(store, runner, notify, poll_interval=0.01)
    worker.start()
    t = store.create("app", "codex", MSGS)
    worker.wake()
    done = await wait_status(store, t.id, DONE)
    await worker.stop()
    assert done.result == "ok:do it"
    assert notified and notified[0].status == DONE


async def test_worker_retry_then_fail(store: TaskStore) -> None:
    calls = []

    async def runner(task: Task) -> str:
        calls.append(task.attempts)
        raise RuntimeError("nope")

    worker = Worker(store, runner, poll_interval=0.01, retry_backoff=0)
    worker.start()
    t = store.create("app", "codex", MSGS, max_attempts=2)
    failed = await wait_status(store, t.id, FAILED)
    await worker.stop()
    assert calls == [1, 2]
    assert "RuntimeError: nope" in failed.error


async def test_worker_cancel_running(store: TaskStore) -> None:
    started = asyncio.Event()

    async def runner(task: Task) -> str:
        started.set()
        await asyncio.sleep(30)
        return "never"

    worker = Worker(store, runner, poll_interval=0.01)
    worker.start()
    t = store.create("app", "codex", MSGS)
    await asyncio.wait_for(started.wait(), 3)
    assert await worker.cancel(t.id)
    await wait_status(store, t.id, CANCELLED)
    await worker.stop()


async def test_worker_stop_requeues_running(store: TaskStore) -> None:
    started = asyncio.Event()

    async def runner(task: Task) -> str:
        started.set()
        await asyncio.sleep(30)
        return "never"

    worker = Worker(store, runner, poll_interval=0.01)
    worker.start()
    t = store.create("app", "codex", MSGS)
    await asyncio.wait_for(started.wait(), 3)
    await worker.stop()
    task = store.get(t.id)
    assert task.status == QUEUED and task.attempts == 0


async def test_webhook_signed() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["sig"] = req.headers[SIGNATURE_HEADER]
        seen["body"] = req.content
        return httpx.Response(200)

    sender = WebhookSender("s3cret", transport=httpx.MockTransport(handler))
    assert await sender.send("http://app/hook", "task.done", {"id": "1"})
    assert verify(seen["body"], "s3cret", seen["sig"])
    assert json.loads(seen["body"]) == {"event": "task.done", "id": "1"}
    failing = WebhookSender("s", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert not await failing.send("http://app/hook", "x", {})


def test_usage_persistence(tmp_path: Path) -> None:
    meter = UsageMeter()
    meter.record("coder", 10, 5, 0.5)
    meter.save(tmp_path / "u.json")
    other = UsageMeter()
    other.load(tmp_path / "u.json")
    assert other.snapshot()["coder"]["prompt_tokens"] == 10
