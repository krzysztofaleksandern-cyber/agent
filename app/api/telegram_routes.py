"""Inbound Telegram webhook: the owner's messages become tasks for Jarvis."""

import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.connectors.telegram import parse_update

router = APIRouter(prefix="/v1/telegram")
log = logging.getLogger(__name__)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
) -> dict[str, bool]:
    settings = request.app.state.settings
    secret = settings.telegram_webhook_secret.get_secret_value()
    if not secret or x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=401, detail={"message": "bad webhook secret"})
    update = await request.json()
    parsed = parse_update(update)
    if parsed is None:
        return {"ok": True}  # nothing to do (non-text update)
    chat_id, text = parsed
    allowed = settings.telegram_allowed_list
    if allowed and chat_id not in allowed:
        log.info("telegram: ignoring message from chat %s (not allowlisted)", chat_id)
        return {"ok": True}
    await asyncio.to_thread(
        request.app.state.tasks.create,
        f"telegram:{chat_id}",
        "jarvis",
        [{"role": "user", "content": text}],
        None,
        settings.task_max_attempts,
    )
    request.app.state.worker.wake()
    return {"ok": True}
