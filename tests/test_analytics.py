from pathlib import Path

import pytest

from app.agents.profiles import AgentRegistry
from app.connectors.analytics import business_summary, render_summary, summarize_csv
from app.connectors.analytics_tools import ANALYTICS_TOOLS
from app.connectors.crm import CrmStore
from app.connectors.invoicing import InvoiceStore
from app.llm.registry import load_config
from app.tools.base import ToolContext, ToolError

ROOT = Path(__file__).parent.parent
CSV = "name,amount,city\nA,100,Kraków\nB,250,Wien\nC,50,Kraków\n"


def test_summarize_csv() -> None:
    out = summarize_csv(CSV)
    assert "rows: 3" in out
    assert "amount (numeric): sum=400" in out and "avg=133.33" in out and "max=250" in out
    assert "city (text)" in out and "Kraków" in out
    assert summarize_csv("") == "(empty CSV)"


def test_business_summary(tmp_path: Path) -> None:
    inv = InvoiceStore(tmp_path / "i.db")
    crm = CrmStore(tmp_path / "c.db")
    items = [{"description": "x", "qty": 1, "unit_price": 1000, "vat_rate": 0}]
    a = inv.create("K1", items)
    inv.create("K2", items)
    inv.set_status(a.number, "paid")
    c = crm.add_contact("Jan", "j@x.pl")
    crm.add_deal(c.id, "Deal", value=5000, stage="qualified")
    kpis = business_summary(inv.list(), crm.list_deals())
    assert kpis["invoices_total"] == 2 and kpis["invoiced_gross"] == 2000
    assert kpis["paid_gross"] == 1000 and kpis["unpaid_gross"] == 1000
    assert kpis["deals_by_stage"] == {"qualified": 1} and kpis["open_pipeline_value"] == 5000
    assert "Podsumowanie" in render_summary(kpis)


async def test_analytics_tools(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "data.csv").write_text(CSV)
    inv = InvoiceStore(tmp_path / "i.db")
    crm = CrmStore(tmp_path / "c.db")
    ctx = ToolContext(
        workspace=ws,
        sandbox=None,
        services={"invoices": inv, "crm": crm},  # type: ignore[arg-type]
    )
    out = await ANALYTICS_TOOLS["analyze_csv"].handler({"path": "data.csv"}, ctx)
    assert "rows: 3" in out
    report = await ANALYTICS_TOOLS["business_report"].handler({}, ctx)
    assert "Podsumowanie" in report
    with pytest.raises(ToolError, match="not a file"):
        await ANALYTICS_TOOLS["analyze_csv"].handler({"path": "nope.csv"}, ctx)


async def test_business_report_unavailable(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, sandbox=None)  # type: ignore[arg-type]
    with pytest.raises(ToolError, match="not available"):
        await ANALYTICS_TOOLS["business_report"].handler({}, ctx)


def test_analyst_agent_valid() -> None:
    aliases = load_config(ROOT / "config/models.yaml", {"OLLAMA_URL": "x", "GEMINI_API_KEYS": "k"})
    reg = AgentRegistry(ROOT / "config/agents.yaml", aliases.models)
    assert "analyst" in reg.names() and "business_report" in reg.get("analyst").tools
