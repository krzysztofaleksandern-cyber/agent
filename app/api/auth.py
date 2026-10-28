"""Bearer-token authentication for the public API."""

import asyncio
import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    label: str
    is_admin: bool = False


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"message": "invalid or missing API key", "type": "invalid_request_error"},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_api_key(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> Principal:
    if creds is None:
        raise _unauthorized()
    token = creds.credentials
    admin_key = request.app.state.settings.admin_api_key.get_secret_value()
    if admin_key and hmac.compare_digest(token.encode(), admin_key.encode()):
        return Principal(label="admin", is_admin=True)
    record = await asyncio.to_thread(request.app.state.keys.verify, token)
    if record is None:
        raise _unauthorized()
    return Principal(label=record.label)


async def require_admin(principal: Principal = Depends(require_api_key)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail={"message": "admin key required"})
    return principal
