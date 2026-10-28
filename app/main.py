"""FastAPI application factory and dependency wiring."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI

from app.agents.profiles import AgentRegistry
from app.api.keys import KeyStore
from app.api.routes import router as api_router
from app.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.registry import ModelRegistry, load_config
from app.logging import setup_logging

log = logging.getLogger(__name__)


def _app_version() -> str:
    try:
        return version("devagent")
    except PackageNotFoundError:
        return "0.0.0"


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    """`llm` overrides the model registry (tests); it must expose the registry interface."""
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("starting env=%s", settings.app_env)
        if llm is None:
            env = {**os.environ, "OLLAMA_URL": settings.ollama_url}
            app.state.llm = ModelRegistry(load_config(settings.models_config, env), env)
        else:
            app.state.llm = llm
        app.state.agents = AgentRegistry(settings.agents_config, app.state.llm.aliases())
        app.state.keys = KeyStore(settings.db_path)
        if not settings.admin_api_key.get_secret_value():
            log.warning("ADMIN_API_KEY is not set; admin endpoints are disabled")
        yield
        app.state.keys.close()
        if llm is None:
            await app.state.llm.aclose()
        log.info("shutting down")

    app = FastAPI(title="devagent", version=_app_version(), lifespan=lifespan)
    app.state.settings = settings
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app
