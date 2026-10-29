"""Telegram Bot API client (send messages). Inbound updates arrive via a webhook route."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class TelegramClient:
    def __init__(
        self, token: str, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}", timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def send_message(self, chat_id: str | int, text: str) -> bool:
        # Telegram caps messages at 4096 chars; send the first chunk and note truncation.
        if len(text) > 4096:
            text = text[:4000] + "\n…(skrócono)"
        try:
            resp = await self._http.post("/sendMessage", json={"chat_id": chat_id, "text": text})
        except httpx.HTTPError as exc:
            log.warning("telegram send failed: %s", type(exc).__name__)
            return False
        return resp.status_code < 400

    async def set_webhook(self, url: str, secret_token: str = "") -> bool:
        payload: dict = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        resp = await self._http.post("/setWebhook", json=payload)
        return resp.status_code < 400


def parse_update(update: dict) -> tuple[str, str] | None:
    """Extract (chat_id, text) from a Telegram update, or None if it carries no text."""
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    text = message.get("text")
    chat_id = chat.get("id")
    if chat_id is None or not text:
        return None
    return str(chat_id), str(text)
