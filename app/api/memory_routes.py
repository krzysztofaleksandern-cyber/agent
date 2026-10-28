"""Feedback and lesson management."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.auth import Principal, require_admin, require_api_key

router = APIRouter(prefix="/v1")


class Feedback(BaseModel):
    interaction_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)


class LessonIn(BaseModel):
    agent: str  # agent name, or "*" for all agents
    text: str = Field(min_length=3, max_length=1000)


@router.post("/feedback")
async def feedback(
    body: Feedback, request: Request, principal: Principal = Depends(require_api_key)
) -> dict[str, Any]:
    memory = request.app.state.memory
    interaction = await asyncio.to_thread(memory.store.get_interaction, body.interaction_id)
    if interaction is None or (interaction.client != principal.label and not principal.is_admin):
        raise HTTPException(status_code=404, detail={"message": "interaction not found"})
    await memory.feedback(body.interaction_id, body.rating, body.comment)
    return {"interaction_id": body.interaction_id, "rating": body.rating}


@router.get("/admin/lessons")
async def list_lessons(
    request: Request, agent: str | None = None, _: Principal = Depends(require_admin)
) -> list[dict[str, Any]]:
    return [lesson.public() for lesson in request.app.state.memory.store.lessons(agent)]


@router.post("/admin/lessons")
async def add_lesson(
    body: LessonIn, request: Request, _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    if body.agent != "*" and request.app.state.agents.get(body.agent) is None:
        raise HTTPException(status_code=404, detail={"message": "unknown agent"})
    lesson_id = await request.app.state.memory.add_lesson(body.agent, body.text, "owner")
    return {"id": lesson_id}


@router.delete("/admin/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: int, request: Request, _: Principal = Depends(require_admin)
) -> dict[str, Any]:
    if not request.app.state.memory.store.delete_lesson(lesson_id):
        raise HTTPException(status_code=404, detail={"message": "lesson not found"})
    return {"deleted": lesson_id}
