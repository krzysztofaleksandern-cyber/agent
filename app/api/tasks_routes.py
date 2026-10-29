"""Background task endpoints."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.api.auth import Principal, require_api_key
from app.tasks.store import Task

router = APIRouter(prefix="/v1/tasks")


class TaskCreate(BaseModel):
    agent: str
    input: str | None = None
    messages: list[dict[str, Any]] | None = None
    webhook_url: str | None = Field(default=None, pattern=r"^https?://")
    max_attempts: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def _one_input(self) -> "TaskCreate":
        if bool(self.input) == bool(self.messages):
            raise ValueError("provide exactly one of 'input' or 'messages'")
        return self


def _owned(request: Request, principal: Principal, task_id: str) -> Task:
    task = request.app.state.tasks.get(task_id)
    if task is None or (task.client != principal.label and not principal.is_admin):
        raise HTTPException(status_code=404, detail={"message": "task not found"})
    return task


@router.post("", status_code=202)
async def create_task(
    body: TaskCreate, request: Request, principal: Principal = Depends(require_api_key)
) -> dict[str, Any]:
    state = request.app.state
    if state.agents.get(body.agent) is None and body.agent not in state.llm.aliases():
        raise HTTPException(status_code=404, detail={"message": f"unknown agent {body.agent!r}"})
    messages = body.messages or [{"role": "user", "content": body.input}]
    task = await asyncio.to_thread(
        state.tasks.create,
        principal.label,
        body.agent,
        messages,
        body.webhook_url,
        body.max_attempts or state.settings.task_max_attempts,
    )
    state.worker.wake()
    return task.public()


@router.get("")
async def list_tasks(
    request: Request, status: str | None = None, principal: Principal = Depends(require_api_key)
) -> list[dict[str, Any]]:
    client = None if principal.is_admin else principal.label
    return [t.public() for t in request.app.state.tasks.list(client=client, status=status)]


@router.get("/{task_id}")
async def get_task(
    task_id: str, request: Request, principal: Principal = Depends(require_api_key)
) -> dict[str, Any]:
    return _owned(request, principal, task_id).public()


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str, request: Request, principal: Principal = Depends(require_api_key)
) -> dict[str, Any]:
    _owned(request, principal, task_id)
    cancelled = await request.app.state.worker.cancel(task_id)
    return {"id": task_id, "cancelled": cancelled}
