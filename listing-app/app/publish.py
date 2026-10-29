"""Publish a listing to marketplaces. Without API tokens, returns a manual draft
(prefilled fields + the portal's 'new listing' URL) so you can post with one paste."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

import httpx


class PublishError(Exception):
    """Publishing failed."""


class NotConfigured(PublishError):
    """No API token for this marketplace; use the manual draft instead."""


class Publisher(Protocol):
    name: str

    async def publish(self, listing: dict[str, Any]) -> dict[str, Any]: ...


def manual_draft(portal: str, new_url: str, listing: dict[str, Any]) -> dict[str, Any]:
    body = f"{listing.get('title', '')}\n\n{listing.get('description', '')}"
    return {
        "mode": "manual",
        "portal": portal,
        "open_url": new_url,
        "title": listing.get("title", ""),
        "price_pln": listing.get("price_pln"),
        "copy_text": body,
        "share_mailto": (
            f"mailto:?subject={quote(str(listing.get('title', '')))}&body={quote(body)}"
        ),
        "note": f"Dodaj ogłoszenie na {portal}: otwórz open_url i wklej copy_text.",
    }


class AllegroPublisher:
    name = "allegro"

    def __init__(
        self, token: str, api_url: str = "https://api.allegro.pl",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:  # fmt: skip
        self.token = token
        self._http = httpx.AsyncClient(
            base_url=api_url.rstrip("/"), timeout=30, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def offer_payload(self, listing: dict[str, Any]) -> dict[str, Any]:
        # Minimal Allegro /sale/product-offers shape (real use needs category + params).
        return {
            "name": listing.get("title", "")[:75],
            "description": {
                "sections": [
                    {"items": [{"type": "TEXT", "content": listing.get("description", "")}]}
                ]
            },
            "sellingMode": {
                "format": "BUY_NOW",
                "price": {"amount": str(listing.get("price_pln", 0)), "currency": "PLN"},
            },
        }

    async def publish(self, listing: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise NotConfigured("set ALLEGRO_TOKEN to post via the API")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.allegro.public.v1+json",
            "Content-Type": "application/vnd.allegro.public.v1+json",
        }
        try:
            resp = await self._http.post(
                "/sale/product-offers", json=self.offer_payload(listing), headers=headers
            )
        except httpx.HTTPError as exc:
            raise PublishError(f"allegro unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise PublishError(f"allegro HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return {"mode": "api", "portal": "allegro", "offer_id": data.get("id"), "raw": data}


class OlxPublisher:
    name = "olx"

    def __init__(
        self, token: str, api_url: str = "https://www.olx.pl/api",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:  # fmt: skip
        self.token = token
        self._http = httpx.AsyncClient(
            base_url=api_url.rstrip("/"), timeout=30, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def publish(self, listing: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise NotConfigured("set OLX_TOKEN to post via the API")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        payload = {
            "title": listing.get("title", ""),
            "description": listing.get("description", ""),
            "price": {"value": listing.get("price_pln", 0), "currency": "PLN"},
        }
        try:
            resp = await self._http.post("/partner/adverts", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise PublishError(f"olx unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise PublishError(f"olx HTTP {resp.status_code}: {resp.text[:200]}")
        return {"mode": "api", "portal": "olx", "raw": resp.json()}


NEW_URLS = {
    "olx": "https://www.olx.pl/d/nowe-ogloszenie/",
    "allegro": "https://allegro.pl/sprzedaz/nowa-oferta",
}
