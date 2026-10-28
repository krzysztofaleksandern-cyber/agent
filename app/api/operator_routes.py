"""Endpoints for the host worker running on the owner's computer.

The worker authenticates with a dedicated bearer token (OPERATOR_WORKER_TOKEN), separate
from client API keys. It long-polls for commands and posts back results.
"""

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.api.auth import Principal, require_admin

router = APIRouter(prefix="/v1/operator")
_bearer = HTTPBearer(auto_error=False)


class Result(BaseModel):
    id: str
    ok: bool = True
    output: str = ""
    error: str | None = None


async def require_worker(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> None:
    token = request.app.state.settings.operator_worker_token.get_secret_value()
    if not token or creds is None or not hmac.compare_digest(creds.credentials, token):
        raise HTTPException(status_code=401, detail={"message": "invalid worker token"})


@router.post("/poll")
async def poll(request: Request, _: None = Depends(require_worker)) -> dict[str, Any]:
    cmd = await request.app.state.operator.poll()
    return {"command": cmd}


@router.post("/result")
async def result(
    body: Result, request: Request, _: None = Depends(require_worker)
) -> dict[str, Any]:
    accepted = request.app.state.operator.submit_result(
        body.id, {"ok": body.ok, "output": body.output, "error": body.error}
    )
    return {"accepted": accepted}


@router.get("/status")
async def status(request: Request, _: Principal = Depends(require_admin)) -> dict[str, Any]:
    return request.app.state.operator.status()
