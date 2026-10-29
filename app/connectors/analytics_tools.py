"""Analyst tools: summarize a CSV file and compute a business KPI snapshot."""

from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.analytics import business_summary, render_summary, summarize_csv
from app.tools.base import Tool, ToolContext, ToolError, jail


async def analyze_csv(args: dict[str, Any], ctx: ToolContext) -> str:
    path = jail(ctx.workspace, str(args.get("path") or ""))
    if not path.is_file():
        raise ToolError(f"not a file: {args.get('path')}")
    return summarize_csv(path.read_text(errors="replace"))


async def business_report(args: dict[str, Any], ctx: ToolContext) -> str:
    invoices_store = ctx.services.get("invoices")
    crm_store = ctx.services.get("crm")
    if invoices_store is None or crm_store is None:
        raise ToolError("business data (invoices/CRM) is not available")
    invoices = await asyncio.to_thread(invoices_store.list)
    deals = await asyncio.to_thread(crm_store.list_deals)
    return render_summary(business_summary(invoices, deals))


ANALYTICS_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "analyze_csv",
            "Summarize a CSV file in /workspace (row/column stats, numeric "
            "aggregates, top values).",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            analyze_csv,
        ),
        Tool(
            "business_report",
            "Compute a business summary from invoices and CRM deals.",
            {"type": "object", "properties": {}, "required": []},
            business_report,
        ),
    ]
}
