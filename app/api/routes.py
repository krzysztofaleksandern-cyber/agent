"""OpenAI-compatible public endpoints."""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import Principal, require_admin, require_api_key
from app.llm.types import LLMBadResponse, LLMResponse, LLMUnavailable

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[dict[str, Any]] = Field(min_length=1)
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


def _error(status: int, message: str, err_type: str, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"message": message, "type": err_type, "code": code}}
    )


def _completion_body(resp: LLMResponse, model: str, cid: str, created: int) -> dict[str, Any]:
    return {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "message": resp.to_message(), "finish_reason": resp.finish_reason}
        ],
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        },
    }


async def _sse(resp: LLMResponse, model: str, cid: str, created: int) -> AsyncIterator[str]:
    """SSE in OpenAI chunk format. The full reply is produced first (agents run tools before
    answering), then emitted as a single delta."""
    base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}
    delta = resp.to_message()
    chunks = [
        {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": resp.finish_reason}]},
    ]
    for chunk in chunks:
        yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatRequest, request: Request, principal: Principal = Depends(require_api_key)
) -> JSONResponse | StreamingResponse:
    llm = request.app.state.llm
    model = body.model or llm.config.default
    log.info("chat client=%s model=%s messages=%d", principal.label, model, len(body.messages))
    try:
        resp = await llm.chat(
            body.messages,
            model=model,
            tools=body.tools,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
    except KeyError:
        return _error(404, f"model {model!r} not found", "invalid_request_error", "model_not_found")
    except LLMUnavailable as exc:
        return _error(503, f"model backend unavailable: {exc}", "server_error")
    except LLMBadResponse as exc:
        return _error(502, f"model backend error: {exc}", "server_error")

    cid, created = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time())
    if body.stream:
        return StreamingResponse(_sse(resp, model, cid, created), media_type="text/event-stream")
    return JSONResponse(_completion_body(resp, model, cid, created))


@router.get("/models")
async def list_models(request: Request, _: Principal = Depends(require_api_key)) -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": alias, "object": "model", "owned_by": "devagent"}
            for alias in request.app.state.llm.aliases()
        ],
    }


@router.get("/admin/usage")
async def usage(request: Request, _: Principal = Depends(require_admin)) -> dict[str, Any]:
    return request.app.state.llm.usage.snapshot()
