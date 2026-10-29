from pathlib import Path

import pytest

from app.agents.profiles import AgentRegistry
from app.connectors.crm import CrmError, CrmStore
from app.connectors.crm_tools import CRM_TOOLS
from app.llm.registry import load_config
from app.tools.base import ToolContext, ToolError

ROOT = Path(__file__).parent.parent


@pytest.fixture
def crm(tmp_path: Path) -> CrmStore:
    return CrmStore(tmp_path / "crm.db")


def ctx(crm: CrmStore) -> ToolContext:
    return ToolContext(workspace=None, sandbox=None, services={"crm": crm})  # type: ignore[arg-type]


def test_contacts_dedupe_by_email(crm: CrmStore) -> None:
    a = crm.add_contact("Jan", "jan@x.pl", company="StackLogic")
    b = crm.add_contact("Jan K", "JAN@x.pl")  # same email, case-insensitive
    assert a.id == b.id
    assert crm.find_contacts("stacklogic")[0].id == a.id
    with pytest.raises(CrmError):
        crm.add_contact("  ")


def test_deal_flow(crm: CrmStore) -> None:
    c = crm.add_contact("Anna", "anna@x.pl")
    d = crm.add_deal(c.id, "Strona WWW", value=5000, source="polecenie")
    assert d.stage == "new"
    assert crm.set_stage(d.id, "qualified").stage == "qualified"
    assert [x.id for x in crm.list_deals(stage="qualified")] == [d.id]
    assert crm.list_deals(stage="won") == []
    with pytest.raises(CrmError, match="stage"):
        crm.set_stage(d.id, "bogus")
    with pytest.raises(CrmError, match="unknown contact"):
        crm.add_deal("nope", "x")


def test_capture_lead(crm: CrmStore) -> None:
    res = crm.capture_lead("Firma XYZ", "biuro@xyz.pl", message="Chcę stronę")
    assert crm.get_contact(res["contact_id"]).email == "biuro@xyz.pl"
    deal = crm.get_deal(res["deal_id"])
    assert deal.stage == "new" and deal.source == "website"


async def test_crm_tools(crm: CrmStore) -> None:
    c = ctx(crm)
    out = await CRM_TOOLS["crm_add_contact"].handler(
        {"name": "Piotr", "email": "p@x.pl", "company": "Nexum"}, c
    )
    assert "Piotr" in out
    found = await CRM_TOOLS["crm_find_contact"].handler({"query": "nexum"}, c)
    cid = found.split("]")[0].strip("[")
    deal_out = await CRM_TOOLS["crm_add_deal"].handler(
        {"contact_id": cid, "title": "Audyt", "value": 2000}, c
    )
    assert "Audyt" in deal_out and "[new]" in deal_out
    did = deal_out.split()[1].rstrip(":")
    assert "qualified" in await CRM_TOOLS["crm_set_stage"].handler(
        {"deal_id": did, "stage": "qualified"}, c
    )
    assert "Audyt" in await CRM_TOOLS["crm_list_deals"].handler({}, c)
    with pytest.raises(ToolError):
        await CRM_TOOLS["crm_add_deal"].handler({"contact_id": "x", "title": "y"}, c)


async def test_crm_tool_unavailable() -> None:
    bare = ToolContext(workspace=None, sandbox=None)  # type: ignore[arg-type]
    with pytest.raises(ToolError, match="not available"):
        await CRM_TOOLS["crm_list_deals"].handler({}, bare)


def test_sales_support_agents_valid() -> None:
    aliases = load_config(ROOT / "config/models.yaml", {"OLLAMA_URL": "x", "GEMINI_API_KEYS": "k"})
    reg = AgentRegistry(ROOT / "config/agents.yaml", aliases.models)
    assert {"sales", "support"} <= set(reg.names())
    assert "crm_add_deal" in reg.get("sales").tools
