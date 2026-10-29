"""Agent tools for the CRM (ToolContext.services['crm'])."""

from __future__ import annotations

import asyncio
from typing import Any

from app.connectors.crm import CrmError
from app.tools.base import Tool, ToolContext, ToolError


def _crm(ctx: ToolContext) -> Any:
    crm = ctx.services.get("crm")
    if crm is None:
        raise ToolError("CRM is not available")
    return crm


async def crm_add_contact(args: dict[str, Any], ctx: ToolContext) -> str:
    crm = _crm(ctx)
    try:
        c = await asyncio.to_thread(
            crm.add_contact, str(args.get("name") or ""), str(args.get("email") or ""),
            str(args.get("phone") or ""), str(args.get("company") or ""),
        )  # fmt: skip
    except CrmError as exc:
        raise ToolError(str(exc)) from exc
    return f"contact {c.id}: {c.name}" + (f" <{c.email}>" if c.email else "")


async def crm_find_contact(args: dict[str, Any], ctx: ToolContext) -> str:
    crm = _crm(ctx)
    found = await asyncio.to_thread(crm.find_contacts, str(args.get("query") or ""))
    if not found:
        return "(no matching contacts)"
    return "\n".join(
        f"[{c.id}] {c.name}"
        + (f" <{c.email}>" if c.email else "")
        + (f" @ {c.company}" if c.company else "")
        for c in found
    )


async def crm_add_deal(args: dict[str, Any], ctx: ToolContext) -> str:
    crm = _crm(ctx)
    value = args.get("value")
    try:
        d = await asyncio.to_thread(
            crm.add_deal, str(args.get("contact_id") or ""), str(args.get("title") or ""),
            float(value) if value is not None else None, str(args.get("source") or ""),
            str(args.get("notes") or ""),
        )  # fmt: skip
    except (CrmError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    return f"deal {d.id}: {d.title} [{d.stage}]"


async def crm_list_deals(args: dict[str, Any], ctx: ToolContext) -> str:
    crm = _crm(ctx)
    try:
        deals = await asyncio.to_thread(crm.list_deals, str(args.get("stage") or ""))
    except CrmError as exc:
        raise ToolError(str(exc)) from exc
    if not deals:
        return "(no deals)"
    return "\n".join(
        f"[{d.id}] {d.title} — {d.stage}" + (f" — {d.value}" if d.value else "") for d in deals
    )


async def crm_set_stage(args: dict[str, Any], ctx: ToolContext) -> str:
    crm = _crm(ctx)
    try:
        d = await asyncio.to_thread(
            crm.set_stage, str(args.get("deal_id") or ""), str(args.get("stage") or "")
        )
    except CrmError as exc:
        raise ToolError(str(exc)) from exc
    return f"deal {d.id} is now {d.stage}"


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


CRM_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "crm_add_contact",
            "Add (or find by email) a CRM contact.",
            _obj(
                {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "company": {"type": "string"},
                },
                ["name"],
            ),
            crm_add_contact,
        ),
        Tool(
            "crm_find_contact",
            "Search CRM contacts by name, email or company.",
            _obj({"query": {"type": "string"}}, ["query"]),
            crm_find_contact,
        ),
        Tool(
            "crm_add_deal",
            "Create a deal for a contact (contact_id from crm_find_contact).",
            _obj(
                {
                    "contact_id": {"type": "string"},
                    "title": {"type": "string"},
                    "value": {"type": "number"},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                ["contact_id", "title"],
            ),
            crm_add_deal,
        ),
        Tool(
            "crm_list_deals",
            "List deals, optionally filtered by stage (new/contacted/qualified/won/lost).",
            _obj({"stage": {"type": "string"}}, []),
            crm_list_deals,
        ),
        Tool(
            "crm_set_stage",
            "Move a deal to a new stage.",
            _obj(
                {"deal_id": {"type": "string"}, "stage": {"type": "string"}}, ["deal_id", "stage"]
            ),
            crm_set_stage,
        ),
    ]
}
