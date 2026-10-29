from pathlib import Path

import pytest

from app.connectors.notes import NoteError, NotesStore
from app.connectors.notes_tools import NOTES_TOOLS
from app.tools.base import ToolContext, ToolError


@pytest.fixture
def store(tmp_path: Path) -> NotesStore:
    return NotesStore(tmp_path / "n.db")


def ctx(store: NotesStore) -> ToolContext:
    return ToolContext(workspace=None, sandbox=None, services={"notes": store})  # type: ignore[arg-type]


def test_notes_lifecycle(store: NotesStore) -> None:
    n = store.add("Zadzwonić do klienta")
    assert not n.done
    assert [x.id for x in store.list()] == [n.id]
    assert store.set_done(n.id).done
    assert store.list() == []  # open only
    assert len(store.list(include_done=True)) == 1
    assert store.delete(n.id) and not store.delete(n.id)
    with pytest.raises(NoteError):
        store.add("  ")
    with pytest.raises(NoteError):
        store.set_done("nope")


async def test_notes_tools(store: NotesStore) -> None:
    c = ctx(store)
    out = await NOTES_TOOLS["note_add"].handler({"text": "Kup kawę"}, c)
    nid = out.split()[2].rstrip(":")
    assert "Kup kawę" in await NOTES_TOOLS["note_list"].handler({}, c)
    assert "done" in await NOTES_TOOLS["note_done"].handler({"id": nid}, c)
    assert await NOTES_TOOLS["note_list"].handler({}, c) == "(no notes)"
    assert "deleted" in await NOTES_TOOLS["note_delete"].handler({"id": nid}, c)
    with pytest.raises(ToolError, match="not found"):
        await NOTES_TOOLS["note_delete"].handler({"id": "x"}, c)
