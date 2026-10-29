"""Agent tools for the owner's notes / to-do list (ToolContext.services['notes'])."""

from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.notes import NoteError
from app.tools.base import Tool, ToolContext, ToolError


def _notes(ctx: ToolContext) -> Any:
    store = ctx.services.get("notes")
    if store is None:
        raise ToolError("notes are not available")
    return store


async def note_add(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        n = await asyncio.to_thread(_notes(ctx).add, str(args.get("text") or ""))
    except NoteError as exc:
        raise ToolError(str(exc)) from exc
    return f"added note {n.id}: {n.text}"


async def note_list(args: dict[str, Any], ctx: ToolContext) -> str:
    notes = await asyncio.to_thread(_notes(ctx).list, bool(args.get("include_done")))
    if not notes:
        return "(no notes)"
    return "\n".join(f"[{n.id}] {'x' if n.done else ' '} {n.text}" for n in notes)


async def note_done(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        n = await asyncio.to_thread(_notes(ctx).set_done, str(args.get("id") or ""), True)
    except NoteError as exc:
        raise ToolError(str(exc)) from exc
    return f"done: {n.text}"


async def note_delete(args: dict[str, Any], ctx: ToolContext) -> str:
    if not await asyncio.to_thread(_notes(ctx).delete, str(args.get("id") or "")):
        raise ToolError("note not found")
    return "deleted"


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


NOTES_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "note_add",
            "Add a note / to-do item.",
            _obj({"text": {"type": "string"}}, ["text"]),
            note_add,
        ),
        Tool(
            "note_list",
            "List notes (open by default; include_done=true for all).",
            _obj({"include_done": {"type": "boolean"}}, []),
            note_list,
        ),
        Tool(
            "note_done",
            "Mark a note as done by id.",
            _obj({"id": {"type": "string"}}, ["id"]),
            note_done,
        ),
        Tool(
            "note_delete",
            "Delete a note by id.",
            _obj({"id": {"type": "string"}}, ["id"]),
            note_delete,
        ),
    ]
}
