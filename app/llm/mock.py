"""Scripted LLM for tests and offline development."""

from collections.abc import Callable, Iterable
from typing import Any

from app.llm.types import ChatMessage, LLMResponse, ToolCall, ToolSchema

Reply = str | LLMResponse | Exception | Callable[[list[ChatMessage]], LLMResponse]


class MockLLM:
    """Returns scripted replies in order; the last one repeats when the script runs out."""

    def __init__(self, replies: Iterable[Reply] = ("ok",), model: str = "mock") -> None:
        self._replies = list(replies)
        self.model = model
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": list(messages),
                "model": model,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(messages)
        if isinstance(reply, LLMResponse):
            return reply
        return LLMResponse(content=reply, model=model or self.model, finish_reason="stop")


def tool_reply(name: str, arguments: str = "{}", call_id: str = "call_0") -> LLMResponse:
    """Convenience: an assistant turn that requests a single tool call."""
    return LLMResponse(
        content=None,
        model="mock",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )
