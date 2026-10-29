"""Owner endpoints for pending approvals."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.auth import Principal, require_admin
from app.approvals.gate import parse_answer

router = APIRouter(prefix="/v1/approvals")


class Decision(BaseModel):
    approve: bool | None = None
    answer: str | None = None  # "TAK" / "NIE" / "yes" / "no" ...


@router.get("")
async def list_pending(request: Request, _: Principal = Depends(require_admin)) -> list[dict]:
    return request.app.state.approvals.pending()


@router.post("/{approval_id}")
async def decide(
    approval_id: str, body: Decision, request: Request, _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    approved = body.approve if body.approve is not None else parse_answer(body.answer or "")
    if approved is None:
        raise HTTPException(status_code=422, detail={"message": "answer must be TAK/NIE (yes/no)"})
    if not request.app.state.approvals.resolve(approval_id, approved):
        raise HTTPException(status_code=404, detail={"message": "no such pending approval"})
    return {"id": approval_id, "approved": approved}
