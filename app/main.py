"""FastAPI application factory and dependency wiring."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.logging import setup_logging

log = logging.getLogger(__name__)


def _app_version() -> str:
    try:
        return version("devagent")
    except PackageNotFoundError:
        return "0.0.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("starting env=%s", settings.app_env)
        yield
        log.info("shutting down")

    app = FastAPI(title="devagent", version=_app_version(), lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app
