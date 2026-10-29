"""Text embeddings: Ollama/OpenAI-compatible endpoint, or a hashing fallback."""

import hashlib
import math
import re
from typing import Protocol

import httpx

from app.llm.types import LLMBadResponse, LLMUnavailable

Vector = list[float]


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[Vector]: ...


def cosine(a: Vector, b: Vector) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class HashEmbedder:
    """Bag-of-words feature hashing. No model needed; good enough for keyword-level recall."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[Vector]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> Vector:
        vec = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class OpenAICompatEmbedder:
    """POST {base_url}/embeddings - works with Ollama (/v1) and vLLM."""

    def __init__(
        self,
        base_url: str,
        model: str = "nomic-embed-text",
        api_key: str = "",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def embed(self, texts: list[str]) -> list[Vector]:
        try:
            resp = await self._http.post("/embeddings", json={"model": self.model, "input": texts})
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"embeddings unavailable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise LLMBadResponse(f"embeddings HTTP {resp.status_code}")
        data = sorted(resp.json().get("data", []), key=lambda d: d.get("index", 0))
        if len(data) != len(texts):
            raise LLMBadResponse("embeddings: wrong number of vectors")
        return [list(map(float, d["embedding"])) for d in data]
