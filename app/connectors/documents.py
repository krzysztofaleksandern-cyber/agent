"""Generate .docx and .html documents from light markdown — standard library only.

A .docx is a ZIP of XML parts; we assemble a minimal, valid one (headings, paragraphs,
bullet lists, bold) without any third-party dependency.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path

_BOLD = re.compile(r"\*\*(.+?)\*\*")


@dataclass(frozen=True)
class Block:
    kind: str  # h1 | h2 | h3 | p | li
    text: str


def parse(md: str) -> list[Block]:
    blocks: list[Block] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append(Block("h3", line[4:]))
        elif line.startswith("## "):
            blocks.append(Block("h2", line[3:]))
        elif line.startswith("# "):
            blocks.append(Block("h1", line[2:]))
        elif line.lstrip().startswith(("- ", "* ")):
            blocks.append(Block("li", line.lstrip()[2:]))
        else:
            blocks.append(Block("p", line))
    return blocks


def to_html(md: str, title: str = "") -> str:
    out = [
        "<!doctype html>",
        '<html><head><meta charset="utf-8">',
        f"<title>{escape(title)}</title>",
        "</head><body>",
    ]
    in_list = False
    for b in parse(md):
        if b.kind == "li" and not in_list:
            out.append("<ul>")
            in_list = True
        elif b.kind != "li" and in_list:
            out.append("</ul>")
            in_list = False
        content = _BOLD.sub(r"<strong>\1</strong>", escape(b.text))
        content = content.replace("&lt;strong&gt;", "<strong>").replace(
            "&lt;/strong&gt;", "</strong>"
        )
        tag = {"h1": "h1", "h2": "h2", "h3": "h3", "p": "p", "li": "li"}[b.kind]
        out.append(f"<{tag}>{content}</{tag}>")
    if in_list:
        out.append("</ul>")
    out.append("</body></html>")
    return "\n".join(out)  # fmt: skip


def _run_xml(text: str) -> str:
    """Convert **bold** markup into Word runs; escape the rest."""
    parts: list[str] = []
    pos = 0
    for m in _BOLD.finditer(text):
        if m.start() > pos:
            parts.append(_run(escape(text[pos : m.start()]), bold=False))
        parts.append(_run(escape(m.group(1)), bold=True))
        pos = m.end()
    if pos < len(text):
        parts.append(_run(escape(text[pos:]), bold=False))
    return "".join(parts) or _run("", bold=False)


def _run(text: str, bold: bool) -> str:
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _para_xml(block: Block) -> str:
    style = {
        "h1": "Heading1",
        "h2": "Heading2",
        "h3": "Heading3",
        "li": "ListParagraph",
        "p": None,
    }[block.kind]
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_run_xml(block.text)}</w:p>"  # fmt: skip


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def build_docx(md: str) -> bytes:
    import io

    body = "".join(_para_xml(b) for b in parse(md))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def write_document(md: str, path: str | Path, title: str = "") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".docx":
        p.write_bytes(build_docx(md))
    elif p.suffix in {".html", ".htm"}:
        p.write_text(to_html(md, title))
    else:
        p.write_text(md)
    return p
