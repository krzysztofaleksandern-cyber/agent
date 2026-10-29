"""Admin endpoints for scheduled (recurring) jobs."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.auth import Principal, require_admin
from app.scheduler.jobs import JobError

router = APIRouter(prefix="/v1/admin/jobs")


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    agent: str
    prompt: str = Field(min_length=1, max_length=8000)
    kind: str  # every_minutes | daily | weekly
    value: str  # minutes, or HH:MM, or D:HH:MM


class Toggle(BaseModel):
    enabled: bool


@router.get("")
async def list_jobs(
    request: Request, _: Principal = Depends(require_admin)
) -> list[dict[str, Any]]:
    return [j.public() for j in request.app.state.jobs.list()]


@router.post("", status_code=201)
async def create_job(
    body: JobIn, request: Request, _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    state = request.app.state
    if state.agents.get(body.agent) is None:
        raise HTTPException(status_code=404, detail={"message": f"unknown agent {body.agent!r}"})
    try:
        job = state.jobs.create(body.name, body.agent, body.prompt, body.kind, body.value)
    except JobError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    return job.public()


@router.post("/{job_id}/toggle")
async def toggle_job(
    job_id: str, body: Toggle, request: Request, _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    if not request.app.state.jobs.set_enabled(job_id, body.enabled):
        raise HTTPException(status_code=404, detail={"message": "job not found"})
    return {"id": job_id, "enabled": body.enabled}


@router.delete("/{job_id}")
async def delete_job(
    job_id: str, request: Request, _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    if not request.app.state.jobs.delete(job_id):
        raise HTTPException(status_code=404, detail={"message": "job not found"})
    return {"deleted": job_id}
