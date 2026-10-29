"""LLM client that spreads requests over several API keys for the same backend.

Used for free-tier providers (e.g. Gemini): each key has its own quota, so rotating
through N keys multiplies the usable rate limit. A key that returns 429/5xx is put on a
short cooldown and the next key is tried.
"""

import logging
import time

from app.llm.base import LLMClient
from app.llm.types import ChatMessage, LLMResponse, LLMUnavailable, ToolSchema

log = logging.getLogger(__name__)


class RotatingKeyClient:
    def __init__(self, clients: list[LLMClient], cooldown_s: float = 60.0) -> None:
        if not clients:
            raise ValueError("RotatingKeyClient needs at least one client")
        self._clients = clients
        self.cooldown_s = cooldown_s
        self._next = 0
        self._cooldown_until: dict[int, float] = {}

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        n = len(self._clients)
        now = time.monotonic()
        last_exc: LLMUnavailable | None = None
        for offset in range(n):
            i = (self._next + offset) % n
            if self._cooldown_until.get(i, 0.0) > now:
                continue
            try:
                resp = await self._clients[i].chat(
                    messages,
                    model=model,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except LLMUnavailable as exc:
                self._cooldown_until[i] = now + self.cooldown_s
                log.warning("key #%d rate-limited/unavailable (%s); rotating", i + 1, exc)
                last_exc = exc
                continue
            self._next = (i + 1) % n  # round-robin across healthy keys
            return resp
        assert last_exc is not None
        raise LLMUnavailable(f"all {n} keys exhausted: {last_exc}")

    async def aclose(self) -> None:
        for client in self._clients:
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()
