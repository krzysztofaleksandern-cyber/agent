"""Agent tools for invoicing (ToolContext.services['invoices'])."""

from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.invoicing import InvoiceError
from app.tools.base import Tool, ToolContext, ToolError


def _inv(ctx: ToolContext) -> Any:
    store = ctx.services.get("invoices")
    if store is None:
        raise ToolError("invoicing is not available")
    return store


async def invoice_create(args: dict[str, Any], ctx: ToolContext) -> str:
    store = _inv(ctx)
    items = args.get("items")
    if not isinstance(items, list):
        raise ToolError("'items' must be a list of {description, qty, unit_price, vat_rate}")
    try:
        inv = await asyncio.to_thread(
            store.create, str(args.get("buyer") or ""), items, str(args.get("seller") or ""),
            str(args.get("currency") or "PLN"), str(args.get("due_at") or ""),
            str(args.get("notes") or ""),
        )  # fmt: skip
    except InvoiceError as exc:
        raise ToolError(str(exc)) from exc
    return f"invoice {inv.number}: {inv.gross} {inv.currency} gross (net {inv.net}, VAT {inv.vat})"


async def invoice_list(args: dict[str, Any], ctx: ToolContext) -> str:
    store = _inv(ctx)
    try:
        invoices = await asyncio.to_thread(store.list, str(args.get("status") or ""))
    except InvoiceError as exc:
        raise ToolError(str(exc)) from exc
    if not invoices:
        return "(no invoices)"
    return "\n".join(
        f"[{i.number}] {i.buyer} — {i.gross} {i.currency} — {i.status}" for i in invoices
    )


async def invoice_get(args: dict[str, Any], ctx: ToolContext) -> str:
    store = _inv(ctx)
    inv = await asyncio.to_thread(store.get, str(args.get("id") or ""))
    if inv is None:
        raise ToolError("invoice not found")
    return store.to_markdown(inv)


async def invoice_set_status(args: dict[str, Any], ctx: ToolContext) -> str:
    store = _inv(ctx)
    try:
        inv = await asyncio.to_thread(
            store.set_status, str(args.get("id") or ""), str(args.get("status") or "")
        )
    except InvoiceError as exc:
        raise ToolError(str(exc)) from exc
    return f"invoice {inv.number} is now {inv.status}"


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


INVOICE_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "invoice_create",
            "Issue an invoice. items: list of {description, qty, unit_price, "
            "vat_rate}. Requires the owner's approval.",
            _obj(
                {
                    "buyer": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "object"}},
                    "seller": {"type": "string"},
                    "currency": {"type": "string"},
                    "due_at": {"type": "string"},
                    "notes": {"type": "string"},
                },
                ["buyer", "items"],
            ),
            invoice_create,
        ),
        Tool(
            "invoice_list",
            "List invoices, optionally by status (issued/paid/cancelled).",
            _obj({"status": {"type": "string"}}, []),
            invoice_list,
        ),
        Tool(
            "invoice_get",
            "Show one invoice (by number or id) as formatted text.",
            _obj({"id": {"type": "string"}}, ["id"]),
            invoice_get,
        ),
        Tool(
            "invoice_set_status",
            "Mark an invoice paid/cancelled/issued.",
            _obj({"id": {"type": "string"}, "status": {"type": "string"}}, ["id", "status"]),
            invoice_set_status,
        ),
    ]
}
