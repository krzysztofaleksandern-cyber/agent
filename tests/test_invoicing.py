from pathlib import Path

import pytest

from app.agents.profiles import AgentRegistry
from app.connectors.invoice_tools import INVOICE_TOOLS
from app.connectors.invoicing import InvoiceError, InvoiceStore, compute_totals
from app.llm.registry import load_config
from app.tools.base import ToolContext, ToolError

ROOT = Path(__file__).parent.parent
ITEMS = [
    {"description": "Strona WWW", "qty": 1, "unit_price": 5000, "vat_rate": 23},
    {"description": "Hosting", "qty": 12, "unit_price": 50, "vat_rate": 23},
]


def test_compute_totals() -> None:
    net, vat, gross = compute_totals(ITEMS)
    assert net == 5600.0 and vat == 1288.0 and gross == 6888.0
    with pytest.raises(InvoiceError):
        compute_totals([{"description": "x"}])


@pytest.fixture
def store(tmp_path: Path) -> InvoiceStore:
    return InvoiceStore(tmp_path / "inv.db", seller="StackLogic sp. z o.o.")


def test_numbering_and_create(store: InvoiceStore) -> None:
    a = store.create("Klient A", ITEMS)
    b = store.create("Klient B", ITEMS)
    year = a.number.split("/")[0]
    assert a.number == f"{year}/001" and b.number == f"{year}/002"
    assert a.seller == "StackLogic sp. z o.o." and a.gross == 6888.0
    assert store.get(a.number).id == a.id  # lookup by number
    with pytest.raises(InvoiceError):
        store.create("", ITEMS)
    with pytest.raises(InvoiceError):
        store.create("X", [])


def test_status_and_list(store: InvoiceStore) -> None:
    inv = store.create("Klient", ITEMS)
    assert store.set_status(inv.number, "paid").status == "paid"
    assert [i.number for i in store.list(status="paid")] == [inv.number]
    assert store.list(status="issued") == []
    with pytest.raises(InvoiceError):
        store.set_status(inv.number, "bogus")
    with pytest.raises(InvoiceError):
        store.set_status("nope", "paid")


def test_render(store: InvoiceStore) -> None:
    inv = store.create("Klient", ITEMS, due_at="2026-06-01", notes="Dziękujemy")
    md = store.to_markdown(inv)
    assert "Faktura" in md and "Do zapłaty:** 6888.0 PLN" in md and "Dziękujemy" in md
    html = store.to_html(inv)
    assert "<table>" in html and "6888.0" in html and "Strona WWW" in html


async def test_invoice_tools(store: InvoiceStore) -> None:
    ctx = ToolContext(workspace=None, sandbox=None, services={"invoices": store})  # type: ignore[arg-type]
    out = await INVOICE_TOOLS["invoice_create"].handler({"buyer": "ACME", "items": ITEMS}, ctx)
    assert "6888.0 PLN gross" in out
    num = out.split()[1].rstrip(":")
    assert "ACME" in await INVOICE_TOOLS["invoice_list"].handler({}, ctx)
    assert "Faktura" in await INVOICE_TOOLS["invoice_get"].handler({"id": num}, ctx)
    assert "paid" in await INVOICE_TOOLS["invoice_set_status"].handler(
        {"id": num, "status": "paid"}, ctx
    )
    with pytest.raises(ToolError, match="list of"):
        await INVOICE_TOOLS["invoice_create"].handler({"buyer": "X", "items": "nope"}, ctx)


def test_invoice_create_is_risky() -> None:
    from app.approvals.risk import classify

    assert classify("invoice_create", {"buyer": "X", "items": []}) is not None
    assert classify("invoice_list", {}) is None


def test_bookkeeper_agent_valid() -> None:
    aliases = load_config(ROOT / "config/models.yaml", {"OLLAMA_URL": "x", "GEMINI_API_KEYS": "k"})
    reg = AgentRegistry(ROOT / "config/agents.yaml", aliases.models)
    assert "bookkeeper" in reg.names()
    assert "invoice_create" in reg.get("bookkeeper").tools
