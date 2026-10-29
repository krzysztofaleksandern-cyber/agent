import httpx

from app.connectors.telegram import TelegramClient, parse_update


def test_parse_update() -> None:
    assert parse_update({"message": {"chat": {"id": 123}, "text": "hej"}}) == ("123", "hej")
    assert parse_update({"edited_message": {"chat": {"id": 5}, "text": "x"}}) == ("5", "x")
    assert parse_update({"message": {"chat": {"id": 1}}}) is None  # no text
    assert parse_update({}) is None


async def test_send_message() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        import json

        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    c = TelegramClient("TOKEN", transport=httpx.MockTransport(handler))
    assert await c.send_message(42, "cześć")
    assert seen["path"] == "/botTOKEN/sendMessage"
    assert seen["body"] == {"chat_id": 42, "text": "cześć"}


async def test_send_truncates_long() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        import json

        assert len(json.loads(req.content)["text"]) <= 4096
        return httpx.Response(200)

    c = TelegramClient("T", transport=httpx.MockTransport(handler))
    assert await c.send_message(1, "x" * 5000)


async def test_send_handles_error() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=req)

    assert not await TelegramClient("T", transport=httpx.MockTransport(down)).send_message(1, "y")
