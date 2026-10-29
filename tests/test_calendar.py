from pathlib import Path

import pytest

from app.connectors.calendar import CalendarError, CalendarStore
from app.connectors.calendar_tools import CALENDAR_TOOLS
from app.tools.base import ToolContext, ToolError


@pytest.fixture
def cal(tmp_path: Path) -> CalendarStore:
    return CalendarStore(tmp_path / "cal.db")


def ctx(cal: CalendarStore) -> ToolContext:
    return ToolContext(workspace=None, sandbox=None, services={"calendar": cal})  # type: ignore[arg-type]


def test_create_list_delete(cal: CalendarStore) -> None:
    e = cal.create("Spotkanie", "2026-05-01T09:00", "2026-05-01T10:00", "Biuro")
    assert e.title == "Spotkanie" and e.location == "Biuro"
    assert cal.list()[0].id == e.id
    assert cal.list(start_from="2026-06-01T00:00") == []
    assert cal.delete(e.id) and not cal.delete(e.id)


def test_validation(cal: CalendarStore) -> None:
    with pytest.raises(CalendarError, match="title"):
        cal.create("  ", "2026-05-01T09:00")
    with pytest.raises(CalendarError, match="ISO 8601"):
        cal.create("x", "not-a-date")
    with pytest.raises(CalendarError, match="before start"):
        cal.create("x", "2026-05-01T10:00", "2026-05-01T09:00")


def test_ics_export(cal: CalendarStore) -> None:
    cal.create("Call", "2026-05-01T09:00:00+00:00", "2026-05-01T09:30:00+00:00", notes="daily")
    ics = cal.to_ics(cal.list())
    assert "BEGIN:VCALENDAR" in ics and "SUMMARY:Call" in ics
    assert "DTSTART:20260501T090000Z" in ics and "DESCRIPTION:daily" in ics


async def test_calendar_tools(cal: CalendarStore) -> None:
    c = ctx(cal)
    out = await CALENDAR_TOOLS["calendar_create"].handler(
        {"title": "Dentysta", "start": "2026-05-02T08:00"}, c
    )
    assert "created event" in out
    listed = await CALENDAR_TOOLS["calendar_list"].handler({}, c)
    assert "Dentysta" in listed
    eid = cal.list()[0].id
    assert "deleted" in await CALENDAR_TOOLS["calendar_delete"].handler({"id": eid}, c)
    with pytest.raises(ToolError, match="no event"):
        await CALENDAR_TOOLS["calendar_delete"].handler({"id": "nope"}, c)


async def test_calendar_tool_bad_date(cal: CalendarStore) -> None:
    with pytest.raises(ToolError, match="ISO 8601"):
        await CALENDAR_TOOLS["calendar_create"].handler(
            {"title": "x", "start": "yesterday"}, ctx(cal)
        )


def test_calendar_delete_is_risky() -> None:
    from app.approvals.risk import classify

    assert classify("calendar_delete", {"id": "1"}) is not None
    assert classify("calendar_create", {"title": "x", "start": "2026-01-01T00:00"}) is None
