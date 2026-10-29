from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.scheduler.jobs import JobError, JobStore, compute_next
from app.scheduler.runner import SchedulerLoop

NOW = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)  # a Friday


def test_compute_next_every_minutes() -> None:
    nxt = compute_next("every_minutes", "30", NOW)
    assert datetime.fromtimestamp(nxt, UTC) == datetime(2026, 5, 1, 10, 30, tzinfo=UTC)


def test_compute_next_daily() -> None:
    assert datetime.fromtimestamp(compute_next("daily", "14:30", NOW), UTC).hour == 14
    # time already passed today -> tomorrow
    nxt = datetime.fromtimestamp(compute_next("daily", "09:00", NOW), UTC)
    assert nxt == datetime(2026, 5, 2, 9, 0, tzinfo=UTC)


def test_compute_next_weekly() -> None:
    # Monday (0) 08:00 from a Friday -> next Monday
    nxt = datetime.fromtimestamp(compute_next("weekly", "0:08:00", NOW), UTC)
    assert nxt == datetime(2026, 5, 4, 8, 0, tzinfo=UTC) and nxt.weekday() == 0


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("daily", "25:00"),
        ("daily", "noon"),
        ("weekly", "9:08:00"),
        ("every_minutes", "x"),
        ("bogus", "1"),
    ],
)
def test_invalid_schedules(kind: str, value: str) -> None:
    with pytest.raises(JobError):
        compute_next(kind, value, NOW)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def test_job_crud(store: JobStore) -> None:
    j = store.create("Inbox triage", "secretary", "Review my inbox", "daily", "08:00")
    assert j.enabled and j.next_run > 0
    assert store.list()[0].id == j.id
    assert store.set_enabled(j.id, False)
    assert not store.get(j.id).enabled
    assert store.delete(j.id) and not store.delete(j.id)
    with pytest.raises(JobError):
        store.create("x", "a", "p", "daily", "99:99")


def test_due_and_mark_ran(store: JobStore) -> None:
    j = store.create("ping", "codex", "do it", "every_minutes", "60")
    assert store.due(j.next_run + 1)[0].id == j.id
    assert store.due(j.next_run - 100) == []
    store.mark_ran(j.id, datetime.now(UTC))
    assert store.get(j.id).last_run is not None


async def test_scheduler_fires_due_jobs(store: JobStore) -> None:
    fired: list[str] = []

    async def enqueue(job) -> None:
        fired.append(job.agent)

    from datetime import timedelta

    loop = SchedulerLoop(store, enqueue)
    store.create("a", "secretary", "p", "every_minutes", "60")
    # tick after the job's next_run (created at real now + 60 min) -> it is due
    later = datetime.now(UTC) + timedelta(hours=2)
    assert await loop.tick(later) == 1
    assert fired == ["secretary"]
    # immediately after, next_run is advanced so it is not due again
    assert await loop.tick(later) == 0
