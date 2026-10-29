import json

import httpx
import pytest

from app.vision import Listing, VisionClient, VisionError, parse_listing

GOOD = {
    "title": "Rower górski Kross 26",
    "category": "Rowery",
    "condition": "używany",
    "description": "Sprawny rower górski, koła 26 cali, 21 biegów. Drobne rysy na ramie.",
    "price_pln": 450,
    "price_min_pln": 400,
    "price_max_pln": 550,
    "tags": ["rower", "mtb", "kross"],
    "attributes": {"marka": "Kross", "kolor": "czarny"},
}


def test_parse_listing_defaults() -> None:
    lst = parse_listing({"title": "x"})
    assert isinstance(lst, Listing) and lst.condition == "używany" and lst.price_pln == 0.0
    full = parse_listing(GOOD)
    assert full.price_pln == 450 and full.tags[0] == "rower" and full.attributes["marka"] == "Kross"


def test_parse_price_formats() -> None:
    assert parse_listing({"price_pln": "1 299,50 zł"}).price_pln == 1299.5
    assert parse_listing({"price_pln": "brak"}).price_pln == 0.0


def _client(handler) -> VisionClient:
    return VisionClient("http://llm/v1", "vmodel", transport=httpx.MockTransport(handler))


async def test_describe_success_sends_image() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        reply = {"choices": [{"message": {"content": json.dumps(GOOD)}}]}
        return httpx.Response(200, json=reply)

    lst = await _client(handler).describe(b"\xff\xd8jpeg", "image/jpeg")
    assert lst.title.startswith("Rower")
    content = seen["body"]["messages"][1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_describe_json_in_code_fence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        fenced = "```json\n" + json.dumps(GOOD) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})

    assert (await _client(handler).describe(b"x")).price_pln == 450


async def test_describe_json_embedded_in_text() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        text = "Oto opis:\n" + json.dumps(GOOD) + "\nMiłego!"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    assert (await _client(handler).describe(b"x")).category == "Rowery"


async def test_describe_bad_json() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "nie wiem"}}]})

    with pytest.raises(VisionError):
        await _client(handler).describe(b"x")


async def test_describe_backend_error() -> None:
    with pytest.raises(VisionError, match="HTTP 500"):
        await _client(lambda r: httpx.Response(500)).describe(b"x")
