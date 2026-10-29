"""Admin endpoints for the fine-tuning cycle."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.api.auth import Principal, require_admin

router = APIRouter(prefix="/v1/admin")


class Candidate(BaseModel):
    alias: str
    model: str  # Ollama model name created on the GPU box, e.g. devagent-coder:v3
    note: str | None = None


@router.get("/dataset", response_class=PlainTextResponse)
async def dataset(
    request: Request,
    min_rating: int = 4,
    agent: str | None = None,
    _: Principal = Depends(require_admin),
) -> PlainTextResponse:
    body = request.app.state.learning.dataset(min_rating, agent)
    return PlainTextResponse(body, media_type="application/jsonl")


@router.post("/candidates")
async def candidate(
    body: Candidate, request: Request, _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    try:
        return await request.app.state.learning.evaluate_candidate(
            body.alias, body.model, body.note
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "unknown alias"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.get("/versions")
async def versions(
    request: Request, alias: str | None = None, _: Principal = Depends(require_admin)
) -> list[dict[str, Any]]:
    return [v.public() for v in request.app.state.learning.versions.list(alias)]


@router.post("/versions/{alias}/rollback")
async def rollback(alias: str, request: Request, _: Principal = Depends(require_admin)) -> dict:
    try:
        return await request.app.state.learning.rollback(alias)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "unknown alias"}) from exc
