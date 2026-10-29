"""Turn a product photo into a structured marketplace listing via a vision LLM."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

SYSTEM = """You are an expert Polish marketplace copywriter (OLX, Allegro). From a product
photo, produce a ready-to-post listing for the POLISH market, in Polish. Be accurate and do
not invent details you cannot see. Estimate a fair used/second-hand price in PLN based on the
Polish market. Return ONLY JSON with this shape:
{
 "title": "short catchy title (max 70 chars)",
 "category": "best-guess category",
 "condition": "nowy|używany|uszkodzony",
 "description": "3-6 sentence description with key features and any visible flaws",
 "price_pln": 123,
 "price_min_pln": 100,
 "price_max_pln": 150,
 "tags": ["keyword", "..."],
 "attributes": {"marka": "...", "kolor": "...", "stan": "..."}
}"""


class VisionError(Exception):
    """The vision model failed or returned something unusable."""


@dataclass
class Listing:
    title: str
    category: str
    condition: str
    description: str
    price_pln: float
    price_min_pln: float
    price_max_pln: float
    tags: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _data_url(image: bytes, content_type: str) -> str:
    return f"data:{content_type};base64,{base64.b64encode(image).decode()}"


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError as exc:
            raise VisionError("model did not return valid JSON") from exc
    raise VisionError("model did not return JSON")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ".").replace(" ", "").rstrip("zł"))
    except (ValueError, TypeError):
        return default


def parse_listing(data: dict[str, Any]) -> Listing:
    price = _num(data.get("price_pln"))
    pmin = _num(data.get("price_min_pln"), price)
    pmax = _num(data.get("price_max_pln"), price)
    return Listing(
        title=str(data.get("title") or "Przedmiot na sprzedaż")[:70],
        category=str(data.get("category") or "Inne"),
        condition=str(data.get("condition") or "używany"),
        description=str(data.get("description") or ""),
        price_pln=price,
        price_min_pln=pmin or price,
        price_max_pln=pmax or price,
        tags=[str(t) for t in (data.get("tags") or [])][:10],
        attributes={str(k): v for k, v in (data.get("attributes") or {}).items()},
    )


class VisionClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def describe(self, image: bytes, content_type: str = "image/jpeg") -> Listing:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Opisz ten przedmiot do wystawienia."},
                        {"type": "image_url", "image_url": {"url": _data_url(image, content_type)}},
                    ],
                },
            ],
            "temperature": 0.3,
        }
        try:
            resp = await self._http.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise VisionError(f"vision backend unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise VisionError(f"vision backend HTTP {resp.status_code}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise VisionError("unexpected response shape") from exc
        return parse_listing(_extract_json(content))
