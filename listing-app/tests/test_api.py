import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.vision import VisionClient

GOOD = {
    "title": "Rower górski",
    "category": "Rowery",
    "condition": "używany",
    "description": "Sprawny rower.",
    "price_pln": 450,
    "price_min_pln": 400,
    "price_max_pln": 550,
    "tags": ["rower"],
    "attributes": {},
}


@pytest.fixture
def client():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GOOD)}}]})

    vision = VisionClient("http://llm/v1", "m", transport=httpx.MockTransport(handler))
    app = create_app(Settings(_env_file=None), vision=vision)
    with TestClient(app) as c:
        yield c


def test_health_and_index(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert "snap2list" in client.get("/").text


def test_describe(client: TestClient) -> None:
    r = client.post("/api/describe", files={"photo": ("i.jpg", b"\xff\xd8data", "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Rower górski" and body["price_pln"] == 450
    # empty file rejected
    assert (
        client.post("/api/describe", files={"photo": ("i.jpg", b"", "image/jpeg")}).status_code
        == 400
    )


def test_publish_manual_fallback(client: TestClient) -> None:
    r = client.post("/api/publish/olx", json=GOOD)
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "manual" and d["portal"] == "olx" and "Rower" in d["copy_text"]
    assert client.post("/api/publish/unknown", json=GOOD).status_code == 404
