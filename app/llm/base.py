"""The interface every LLM backend implements."""

from typing import Protocol

from app.llm.types import ChatMessage, LLMResponse, ToolSchema


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...
