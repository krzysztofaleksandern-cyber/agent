"""Model management via Ollama's native API (not part of the OpenAI-compatible surface)."""

from dataclasses import dataclass
from typing import Any

import httpx

from app.llm.types import LLMBadResponse, LLMUnavailable


@dataclass(frozen=True)
class LocalModel:
    name: str
    size_bytes: int
    modified_at: str


class OllamaAdmin:
    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # base_url is the Ollama root (e.g. http://gpu:11434), not the /v1 endpoint.
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/").removesuffix("/v1"), timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise LLMUnavailable(f"ollama unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise LLMBadResponse(f"ollama HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.content else {}

    async def list_models(self) -> list[LocalModel]:
        data = await self._request("GET", "/api/tags")
        return [
            LocalModel(m["name"], int(m.get("size", 0)), m.get("modified_at", ""))
            for m in data.get("models", [])
        ]

    async def pull(self, name: str, pull_timeout: float = 3600.0) -> str:
        """Download a model (blocking until done). Returns final status string."""
        data = await self._request(
            "POST", "/api/pull", json={"model": name, "stream": False}, timeout=pull_timeout
        )
        return str(data.get("status", ""))

    async def is_up(self) -> bool:
        try:
            await self._request("GET", "/api/version")
        except (LLMUnavailable, LLMBadResponse):
            return False
        return True
