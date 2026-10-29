"""Local invoicing: numbered invoices with line items and VAT, stored in SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    seller TEXT NOT NULL,
    buyer TEXT NOT NULL,
    items TEXT NOT NULL,
    currency TEXT NOT NULL,
    net REAL NOT NULL,
    vat REAL NOT NULL,
    gross REAL NOT NULL,
    status TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    due_at TEXT,
    notes TEXT,
    created_at REAL NOT NULL
);
"""

STATUSES = ["issued", "paid", "cancelled"]


class InvoiceError(Exception):
    """Invalid invoice operation."""


@dataclass(frozen=True)
class Invoice:
    id: str
    number: str
    seller: str
    buyer: str
    items: list[dict[str, Any]]
    currency: str
    net: float
    vat: float
    gross: float
    status: str
    issued_at: str
    due_at: str | None
    notes: str | None
    created_at: float

    def public(self) -> dict[str, Any]:
        return {**self.__dict__}


def compute_totals(items: list[dict[str, Any]]) -> tuple[float, float, float]:
    net = vat = 0.0
    for it in items:
        try:
            qty = float(it["qty"])
            price = float(it["unit_price"])
            rate = float(it.get("vat_rate", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvoiceError("each item needs qty, unit_price and optional vat_rate") from exc
        line_net = qty * price
        net += line_net
        vat += line_net * rate / 100.0
    return round(net, 2), round(vat, 2), round(net + vat, 2)


class InvoiceStore:
    def __init__(self, db_path: str | Path, seller: str = "") -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self.default_seller = seller

    def close(self) -> None:
        self._conn.close()

    def _next_number(self, year: int) -> str:
        row = self._conn.execute(
            "SELECT COUNT(*) n FROM invoices WHERE number LIKE ?", (f"{year}/%",)
        ).fetchone()
        return f"{year}/{row['n'] + 1:03d}"

    def create(
        self, buyer: str, items: list[dict[str, Any]], seller: str = "",
        currency: str = "PLN", due_at: str = "", notes: str = "",
    ) -> Invoice:  # fmt: skip
        if not buyer.strip():
            raise InvoiceError("buyer is required")
        if not items:
            raise InvoiceError("at least one line item is required")
        net, vat, gross = compute_totals(items)
        now = datetime.now(UTC)
        invoice_id = f"inv_{int(time.time() * 1000)}"
        with self._lock, self._conn:
            number = self._next_number(now.year)
            self._conn.execute(
                "INSERT INTO invoices (id, number, seller, buyer, items, currency, net, vat,"
                " gross, status, issued_at, due_at, notes, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (invoice_id, number, seller or self.default_seller, buyer.strip(),
                 json.dumps(items), currency, net, vat, gross, "issued",
                 now.date().isoformat(), due_at or None, notes or None, time.time()),
            )  # fmt: skip
        got = self.get(invoice_id)
        assert got is not None
        return got

    def get(self, invoice_id: str) -> Invoice | None:
        row = self._conn.execute(
            "SELECT * FROM invoices WHERE id = ? OR number = ?", (invoice_id, invoice_id)
        ).fetchone()
        return _invoice(row) if row else None

    def list(self, status: str = "") -> list[Invoice]:
        if status and status not in STATUSES:
            raise InvoiceError(f"status must be one of {STATUSES}")
        sql, args = "SELECT * FROM invoices", []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        rows = self._conn.execute(sql + " ORDER BY created_at DESC", args).fetchall()
        return [_invoice(r) for r in rows]

    def set_status(self, invoice_id: str, status: str) -> Invoice:
        if status not in STATUSES:
            raise InvoiceError(f"status must be one of {STATUSES}")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE invoices SET status = ? WHERE id = ? OR number = ?",
                (status, invoice_id, invoice_id),
            )
        if cur.rowcount == 0:
            raise InvoiceError(f"unknown invoice {invoice_id}")
        got = self.get(invoice_id)
        assert got is not None
        return got

    def to_markdown(self, inv: Invoice) -> str:
        lines = [
            f"# Faktura {inv.number}",
            "",
            f"**Sprzedawca:** {inv.seller}",
            f"**Nabywca:** {inv.buyer}",
            f"**Data wystawienia:** {inv.issued_at}",
        ]
        if inv.due_at:
            lines.append(f"**Termin płatności:** {inv.due_at}")
        lines += ["", "## Pozycje"]
        for it in inv.items:
            q, p, r = it["qty"], it["unit_price"], it.get("vat_rate", 0)
            lines.append(f"- {it.get('description', '')}: {q} x {p} {inv.currency} (VAT {r}%)")
        lines += [
            "",
            f"**Netto:** {inv.net} {inv.currency}",
            f"**VAT:** {inv.vat} {inv.currency}",
            f"**Do zapłaty:** {inv.gross} {inv.currency}",
        ]
        if inv.notes:
            lines += ["", inv.notes]
        return "\n".join(lines)  # fmt: skip

    def to_html(self, inv: Invoice) -> str:
        rows = "".join(
            f"<tr><td>{escape(str(it.get('description', '')))}</td><td>{it['qty']}</td>"
            f"<td>{it['unit_price']}</td><td>{it.get('vat_rate', 0)}%</td></tr>"
            for it in inv.items
        )
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><title>Faktura {inv.number}</title>"
            "<style>body{font-family:sans-serif}table{border-collapse:collapse}"
            "td,th{border:1px solid #ccc;padding:6px}</style></head><body>"
            f"<h1>Faktura {escape(inv.number)}</h1>"
            f"<p><b>Sprzedawca:</b> {escape(inv.seller)}<br><b>Nabywca:</b> {escape(inv.buyer)}<br>"
            f"<b>Wystawiono:</b> {inv.issued_at}"
            + (f"<br><b>Termin:</b> {inv.due_at}" if inv.due_at else "")
            + "</p>"
            "<table><tr><th>Opis</th><th>Ilość</th><th>Cena</th><th>VAT</th></tr>"
            f"{rows}</table>"
            f"<p><b>Netto:</b> {inv.net} {inv.currency}<br><b>VAT:</b> {inv.vat} {inv.currency}<br>"
            f"<b>Do zapłaty:</b> {inv.gross} {inv.currency}</p></body></html>"
        )


def _invoice(row: sqlite3.Row) -> Invoice:
    return Invoice(
        row["id"], row["number"], row["seller"], row["buyer"], json.loads(row["items"]),
        row["currency"], row["net"], row["vat"], row["gross"], row["status"],
        row["issued_at"], row["due_at"], row["notes"], row["created_at"],
    )  # fmt: skip
