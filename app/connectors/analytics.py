"""Lightweight analytics: CSV summaries and a business KPI snapshot (stdlib only)."""

from __future__ import annotations

import contextlib
import csv
import io
from typing import Any


def summarize_csv(text: str, max_rows: int = 100_000) -> str:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return "(empty CSV)"
    rows = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(row)
    n = len(rows)
    out = [f"rows: {n}", f"columns: {', '.join(header)}", ""]
    for col_idx, name in enumerate(header):
        values = [r[col_idx] for r in rows if col_idx < len(r) and r[col_idx] != ""]
        nums = _as_numbers(values)
        if nums and len(nums) >= max(1, n // 2):  # mostly numeric
            total = sum(nums)
            out.append(
                f"- {name} (numeric): sum={_fmt(total)} avg={_fmt(total / len(nums))} "
                f"min={_fmt(min(nums))} max={_fmt(max(nums))}"
            )
        else:
            top = _top_values(values, 3)
            summary = ", ".join(f"{v} x{c}" for v, c in top) if top else "(empty)"
            out.append(f"- {name} (text): {len(set(values))} distinct; top: {summary}")
    return "\n".join(out)


def _as_numbers(values: list[str]) -> list[float]:
    nums = []
    for v in values:
        with contextlib.suppress(ValueError):
            nums.append(float(v.replace(",", ".").replace(" ", "")))
    return nums


def _top_values(values: list[str], k: int) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:k]


def _fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


def business_summary(invoices: list[Any], deals: list[Any]) -> dict[str, Any]:
    """KPIs from Invoice and Deal objects (duck-typed: .gross/.status, .stage/.value)."""
    by_status: dict[str, dict[str, float]] = {}
    for inv in invoices:
        bucket = by_status.setdefault(inv.status, {"count": 0, "gross": 0.0})
        bucket["count"] += 1
        bucket["gross"] += float(inv.gross or 0)
    deals_by_stage: dict[str, int] = {}
    pipeline = 0.0
    for d in deals:
        deals_by_stage[d.stage] = deals_by_stage.get(d.stage, 0) + 1
        if d.stage not in {"won", "lost"} and d.value:
            pipeline += float(d.value)
    invoiced = round(sum(b["gross"] for b in by_status.values()), 2)
    paid = round(by_status.get("paid", {}).get("gross", 0.0), 2)
    return {
        "invoices_total": len(invoices),
        "invoiced_gross": invoiced,
        "paid_gross": paid,
        "unpaid_gross": round(invoiced - paid - by_status.get("cancelled", {}).get("gross", 0), 2),
        "invoices_by_status": by_status,
        "deals_by_stage": deals_by_stage,
        "open_pipeline_value": round(pipeline, 2),
    }


def render_summary(kpis: dict[str, Any]) -> str:
    lines = [
        "# Podsumowanie biznesowe",
        "",
        f"- Faktury: {kpis['invoices_total']} (wystawione na {kpis['invoiced_gross']})",
        f"- Zapłacone: {kpis['paid_gross']}, niezapłacone: {kpis['unpaid_gross']}",
        f"- Szanse w toku: wartość {kpis['open_pipeline_value']}",
    ]
    if kpis["deals_by_stage"]:
        stages = ", ".join(f"{s}: {n}" for s, n in kpis["deals_by_stage"].items())
        lines.append(f"- Szanse wg etapu: {stages}")
    return "\n".join(lines)
