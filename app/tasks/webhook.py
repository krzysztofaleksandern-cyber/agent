"""HMAC-signed webhook delivery (task results, approval requests)."""

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Devagent-Signature"


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(body: bytes, secret: str, signature: str) -> bool:
    """Helper for receivers (your apps) to check a delivery."""
    return hmac.compare_digest(sign(body, secret), signature)


class WebhookSender:
    def __init__(
        self,
        secret: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.secret = secret
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def send(self, url: str, event: str, payload: dict[str, Any]) -> bool:
        body = json.dumps({"event": event, **payload}).encode()
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers[SIGNATURE_HEADER] = sign(body, self.secret)
        try:
            resp = await self._http.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("webhook %s to %s failed: %s", event, url, type(exc).__name__)
            return False
        if resp.status_code >= 400:
            log.warning("webhook %s to %s returned %d", event, url, resp.status_code)
            return False
        return True
