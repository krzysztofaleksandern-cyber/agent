"""Phone console (PWA): OTP login, then talk to the operator agent and answer approvals.

A console session is scoped to the `operator` agent and to approving/denying actions;
it is not an admin key.
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.approvals.gate import parse_answer

router = APIRouter(prefix="/console")
_bearer = HTTPBearer(auto_error=False)
_STATIC = Path(__file__).resolve().parent.parent / "console" / "static"
CONSOLE_CLIENT = "console"


class Login(BaseModel):
    otp: str = Field(min_length=4, max_length=12)


class Command(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class Answer(BaseModel):
    answer: str


async def require_session(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> str:
    if creds is None or not request.app.state.console.verify(creds.credentials):
        raise HTTPException(status_code=401, detail={"message": "log in with a one-time password"})
    return creds.credentials


@router.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@router.get("/manifest.webmanifest")
async def manifest() -> FileResponse:
    return FileResponse(_STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(_STATIC / "sw.js", media_type="text/javascript")


@router.post("/api/login")
async def login(body: Login, request: Request) -> dict[str, Any]:
    session = request.app.state.console.redeem(body.otp)
    if session is None:
        raise HTTPException(status_code=401, detail={"message": "invalid or expired code"})
    return {"token": session.token, "expires_at": session.expires_at}


@router.post("/api/logout")
async def logout(request: Request, token: str = Depends(require_session)) -> dict[str, bool]:
    request.app.state.console.logout(token)
    return {"ok": True}


@router.get("/api/status")
async def status(request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
    return request.app.state.operator.status()


@router.post("/api/command", status_code=202)
async def command(
    body: Command, request: Request, _: str = Depends(require_session)
) -> dict[str, Any]:
    import asyncio

    state = request.app.state
    task = await asyncio.to_thread(
        state.tasks.create,
        CONSOLE_CLIENT,
        "operator",
        [{"role": "user", "content": body.text}],
        None,
        state.settings.task_max_attempts,
    )
    state.worker.wake()
    return task.public()


@router.get("/api/command/{task_id}")
async def command_status(
    task_id: str, request: Request, _: str = Depends(require_session)
) -> dict[str, Any]:
    task = request.app.state.tasks.get(task_id)
    if task is None or task.client != CONSOLE_CLIENT:
        raise HTTPException(status_code=404, detail={"message": "not found"})
    return task.public()


@router.get("/api/approvals")
async def approvals(request: Request, _: str = Depends(require_session)) -> list[dict[str, Any]]:
    return request.app.state.approvals.pending()


@router.post("/api/approvals/{approval_id}")
async def answer(
    approval_id: str, body: Answer, request: Request, _: str = Depends(require_session)
) -> dict[str, Any]:
    decision = parse_answer(body.answer)
    if decision is None:
        raise HTTPException(status_code=422, detail={"message": "answer TAK or NIE"})
    if not request.app.state.approvals.resolve(approval_id, decision):
        raise HTTPException(status_code=404, detail={"message": "no such pending approval"})
    return {"id": approval_id, "approved": decision}
