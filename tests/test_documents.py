import io
import zipfile
from pathlib import Path

import pytest

from app.connectors.document_tools import DOCUMENT_TOOLS
from app.connectors.documents import build_docx, parse, to_html, write_document
from app.tools.base import ToolContext, ToolError

MD = "# Oferta\n\n## Zakres\n\nStrona **WWW** z CMS.\n\n- projekt\n- wdrożenie\n"


def test_parse() -> None:
    kinds = [b.kind for b in parse(MD)]
    assert kinds == ["h1", "h2", "p", "li", "li"]


def test_docx_is_valid_zip() -> None:
    data = build_docx(MD)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None
    names = z.namelist()
    assert "[Content_Types].xml" in names and "word/document.xml" in names
    doc = z.read("word/document.xml").decode()
    assert "Heading1" in doc and "Oferta" in doc and "<w:b/>" in doc  # bold run


def test_html() -> None:
    html = to_html(MD, title="Oferta")
    assert "<h1>Oferta</h1>" in html and "<ul>" in html and "<strong>WWW</strong>" in html
    assert "<title>Oferta</title>" in html


def test_write_document_formats(tmp_path: Path) -> None:
    assert write_document(MD, tmp_path / "a.docx").suffix == ".docx"
    assert (tmp_path / "a.docx").read_bytes()[:2] == b"PK"  # zip magic
    assert "<h1>" in (write_document(MD, tmp_path / "a.html")).read_text()
    assert write_document(MD, tmp_path / "a.md").read_text() == MD


async def test_make_document_tool(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = ToolContext(workspace=ws, sandbox=None)  # type: ignore[arg-type]
    out = await DOCUMENT_TOOLS["make_document"].handler({"path": "oferta.docx", "content": MD}, ctx)
    assert "oferta.docx" in out and (ws / "oferta.docx").exists()
    with pytest.raises(ToolError, match="must end with"):
        await DOCUMENT_TOOLS["make_document"].handler({"path": "x.pdf", "content": MD}, ctx)
    with pytest.raises(ToolError, match="required"):
        await DOCUMENT_TOOLS["make_document"].handler({"path": "x.docx"}, ctx)
    with pytest.raises(ToolError):
        await DOCUMENT_TOOLS["make_document"].handler(
            {"path": "../escape.docx", "content": MD}, ctx
        )
