"""Tool to generate .docx / .html / .md documents into the agent workspace."""

from __future__ import annotations

from typing import Any

from app.connectors.documents import write_document
from app.tools.base import Tool, ToolContext, ToolError, jail


async def make_document(args: dict[str, Any], ctx: ToolContext) -> str:
    path = str(args.get("path") or "")
    content = str(args.get("content") or "")
    if not path or not content:
        raise ToolError("arguments 'path' and 'content' (light markdown) are required")
    if not path.endswith((".docx", ".html", ".htm", ".md", ".txt")):
        raise ToolError("path must end with .docx, .html, .md or .txt")
    target = jail(ctx.workspace, path)
    written = write_document(content, target, str(args.get("title") or ""))
    return f"wrote {written.relative_to(ctx.workspace.resolve())} ({written.stat().st_size} bytes)"


MAKE_DOCUMENT = Tool(
    "make_document",
    "Generate a document from light markdown (# headings, - bullets, **bold**). "
    "Choose the format by extension: .docx (Word), .html, .md or .txt.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "title": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    make_document,
)

DOCUMENT_TOOLS = {MAKE_DOCUMENT.name: MAKE_DOCUMENT}
