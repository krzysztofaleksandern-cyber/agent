import httpx
import pytest

from app.publish import (
    AllegroPublisher,
    NotConfigured,
    OlxPublisher,
    PublishError,
    manual_draft,
)

LISTING = {"title": "Rower", "description": "Opis", "price_pln": 450}


def test_manual_draft() -> None:
    d = manual_draft("olx", "https://olx/new", LISTING)
    assert d["mode"] == "manual" and d["portal"] == "olx"
    assert d["open_url"] == "https://olx/new" and "Rower" in d["copy_text"]
    assert d["share_mailto"].startswith("mailto:")


async def test_allegro_not_configured() -> None:
    with pytest.raises(NotConfigured):
        await AllegroPublisher("").publish(LISTING)


async def test_allegro_offer_payload() -> None:
    p = AllegroPublisher("tok")
    payload = p.offer_payload(LISTING)
    assert payload["name"] == "Rower"
    assert payload["sellingMode"]["price"]["amount"] == "450"
    await p.aclose()


async def test_allegro_publish_api() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer tok"
        return httpx.Response(201, json={"id": "offer-1"})

    p = AllegroPublisher("tok", transport=httpx.MockTransport(handler))
    res = await p.publish(LISTING)
    assert res["mode"] == "api" and res["offer_id"] == "offer-1"
    await p.aclose()


async def test_olx_publish_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad")

    p = OlxPublisher("tok", transport=httpx.MockTransport(handler))
    with pytest.raises(PublishError, match="HTTP 400"):
        await p.publish(LISTING)
    await p.aclose()
