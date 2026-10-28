"""Client for any OpenAI-compatible chat-completions endpoint (Ollama, vLLM, llama.cpp)."""

import asyncio
import logging
from typing import Any

import httpx

from app.llm.types import (
    ChatMessage,
    LLMBadResponse,
    LLMResponse,
    LLMTimeout,
    LLMUnavailable,
    ToolCall,
    ToolSchema,
    Usage,
)

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        default_model: str,
        api_key: str = "",
        timeout: float = 120.0,
        max_retries: int = 2,
        backoff: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
        )
        self.default_model = default_model
        self.max_retries = max_retries
        self.backoff = backoff

    async def aclose(self) -> None:
        await self._http.aclose()

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {"model": model or self.default_model, "messages": messages}
        if tools:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        data = await self._post("/chat/completions", payload)
        return _parse_response(data, payload["model"])

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
            try:
                resp = await self._http.post(path, json=payload)
            except httpx.TimeoutException as exc:
                last_exc = LLMTimeout(f"timeout calling {path}")
                log.warning("llm timeout attempt=%d: %s", attempt + 1, type(exc).__name__)
                continue
            except httpx.TransportError as exc:
                last_exc = LLMUnavailable(f"transport error: {type(exc).__name__}")
                log.warning("llm transport error attempt=%d: %s", attempt + 1, type(exc).__name__)
                continue
            if resp.status_code in RETRYABLE_STATUS:
                last_exc = LLMUnavailable(f"HTTP {resp.status_code}")
                log.warning("llm HTTP %d attempt=%d", resp.status_code, attempt + 1)
                continue
            if resp.status_code >= 400:
                raise LLMBadResponse(f"HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                return resp.json()
            except ValueError as exc:
                raise LLMBadResponse("response is not JSON") from exc
        assert last_exc is not None
        raise last_exc


def _parse_response(data: dict[str, Any], requested_model: str) -> LLMResponse:
    try:
        choice = data["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMBadResponse("missing choices[0].message") from exc
    calls = [
        ToolCall(
            id=c.get("id") or f"call_{i}",
            name=c["function"]["name"],
            arguments=c["function"].get("arguments") or "{}",
        )
        for i, c in enumerate(msg.get("tool_calls") or [])
    ]
    usage = data.get("usage") or {}
    return LLMResponse(
        content=msg.get("content"),
        model=data.get("model", requested_model),
        tool_calls=calls,
        finish_reason=choice.get("finish_reason"),
        usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
    )
