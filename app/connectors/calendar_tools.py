"""Agent tools for the local calendar (ToolContext.services['calendar'])."""

import asyncio
from typing import Any

from app.connectors.calendar import CalendarError
from app.tools.base import Tool, ToolContext, ToolError


def _cal(ctx: ToolContext) -> Any:
    cal = ctx.services.get("calendar")
    if cal is None:
        raise ToolError("calendar is not available")
    return cal


async def calendar_list(args: dict[str, Any], ctx: ToolContext) -> str:
    cal = _cal(ctx)
    try:
        events = await asyncio.to_thread(
            cal.list, str(args.get("from") or ""), str(args.get("to") or ""),
            min(int(args.get("limit") or 50), 100),
        )  # fmt: skip
    except CalendarError as exc:
        raise ToolError(str(exc)) from exc
    if not events:
        return "(no events)"
    return "\n".join(
        f"[{e.id}] {e.start}{' - ' + e.end if e.end else ''} — {e.title}"
        f"{' @ ' + e.location if e.location else ''}"
        for e in events
    )


async def calendar_create(args: dict[str, Any], ctx: ToolContext) -> str:
    cal = _cal(ctx)
    try:
        e = await asyncio.to_thread(
            cal.create, str(args.get("title") or ""), str(args.get("start") or ""),
            str(args.get("end") or ""), str(args.get("location") or ""),
            str(args.get("notes") or ""),
        )  # fmt: skip
    except CalendarError as exc:
        raise ToolError(str(exc)) from exc
    return f"created event {e.id}: {e.title} at {e.start}"


async def calendar_delete(args: dict[str, Any], ctx: ToolContext) -> str:
    cal = _cal(ctx)
    event_id = str(args.get("id") or "")
    if not await asyncio.to_thread(cal.delete, event_id):
        raise ToolError(f"no event with id {event_id}")
    return f"deleted event {event_id}"


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


CALENDAR_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "calendar_list",
            "List calendar events, optionally between 'from' and 'to' (ISO 8601 datetimes).",
            _obj(
                {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                [],
            ),
            calendar_list,
        ),
        Tool(
            "calendar_create",
            "Create a calendar event. start/end are ISO 8601 (e.g. 2026-05-01T09:00).",
            _obj(
                {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "location": {"type": "string"},
                    "notes": {"type": "string"},
                },
                ["title", "start"],
            ),
            calendar_create,
        ),
        Tool(
            "calendar_delete",
            "Delete a calendar event by id. Requires the owner's approval.",
            _obj({"id": {"type": "string"}}, ["id"]),
            calendar_delete,
        ),
    ]
}
