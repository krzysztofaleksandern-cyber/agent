"""snap2list API: photo in, ready marketplace listing out, one-click draft to OLX/Allegro."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import Settings, get_settings
from app.publish import (
    NEW_URLS,
    AllegroPublisher,
    NotConfigured,
    OlxPublisher,
    PublishError,
    manual_draft,
)
from app.vision import VisionClient, VisionError

_STATIC = Path(__file__).resolve().parent / "static"
MAX_IMAGE_BYTES = 12_000_000


def create_app(settings: Settings | None = None, vision: VisionClient | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.vision = vision or VisionClient(
            settings.llm_base_url,
            settings.vision_model,
            settings.llm_api_key.get_secret_value(),
            settings.request_timeout,
        )
        yield
        if vision is None:
            await app.state.vision.aclose()

    app = FastAPI(title="snap2list", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.post("/api/describe")
    async def describe(request: Request, photo: UploadFile = File(...)) -> JSONResponse:
        data = await photo.read()
        if not data:
            raise HTTPException(status_code=400, detail={"message": "empty file"})
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail={"message": "image too large"})
        try:
            listing = await request.app.state.vision.describe(
                data, photo.content_type or "image/jpeg"
            )
        except VisionError as exc:
            return JSONResponse(status_code=502, content={"error": str(exc)})
        return JSONResponse(listing.to_dict())

    @app.post("/api/publish/{portal}")
    async def publish(portal: str, request: Request) -> JSONResponse:
        if portal not in NEW_URLS:
            raise HTTPException(status_code=404, detail={"message": "unknown portal"})
        listing: dict[str, Any] = await request.json()
        pub = _publisher(portal, settings)
        if pub is not None:
            try:
                return JSONResponse(await pub.publish(listing))
            except NotConfigured:
                pass  # fall back to a manual draft
            except PublishError as exc:
                return JSONResponse(status_code=502, content={"error": str(exc)})
            finally:
                await pub.aclose()
        return JSONResponse(manual_draft(portal, NEW_URLS[portal], listing))

    return app


def _publisher(portal: str, settings: Settings):
    if portal == "allegro" and settings.allegro_token.get_secret_value():
        return AllegroPublisher(settings.allegro_token.get_secret_value(), settings.allegro_api_url)
    if portal == "olx" and settings.olx_token.get_secret_value():
        return OlxPublisher(settings.olx_token.get_secret_value(), settings.olx_api_url)
    return None
