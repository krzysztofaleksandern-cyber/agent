"""FastAPI application factory and dependency wiring."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI

from app.agents.profiles import AgentRegistry
from app.api.keys import KeyStore
from app.api.routes import router as api_router
from app.api.tasks_routes import router as tasks_router
from app.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.registry import ModelRegistry, load_config
from app.logging import setup_logging
from app.tasks.store import Task, TaskStore
from app.tasks.webhook import WebhookSender
from app.tasks.worker import Worker

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
        usage_path = Path(settings.data_dir) / "usage.json"
        app.state.llm.usage.load(usage_path)
        app.state.webhooks = WebhookSender(settings.webhook_secret.get_secret_value())
        app.state.tasks = TaskStore(settings.db_path)

        async def run_task(task: Task) -> str:
            return await _simple_agent_call(app, task.agent, task.messages)

        async def notify(task: Task) -> None:
            if task.webhook_url:
                await app.state.webhooks.send(
                    task.webhook_url, "task." + task.status, task.public()
                )

        app.state.worker = Worker(
            app.state.tasks,
            run_task,
            notify,
            concurrency=settings.worker_concurrency,
            retry_backoff=settings.task_retry_backoff,
        )
        app.state.worker.start()
        yield
        await app.state.worker.stop()
        app.state.tasks.close()
        await app.state.webhooks.aclose()
        app.state.llm.usage.save(usage_path)
        app.state.keys.close()
        if llm is None:
            await app.state.llm.aclose()
        log.info("shutting down")

    app = FastAPI(title="devagent", version=_app_version(), lifespan=lifespan)
    app.state.settings = settings
    app.include_router(api_router)
    app.include_router(tasks_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app


async def _simple_agent_call(app: FastAPI, name: str, messages: list[dict]) -> str:
    """Single LLM call with the agent's prompt (replaced by the agent loop in Phase 7)."""
    agent = app.state.agents.get(name)
    if agent is not None:
        messages = [{"role": "system", "content": agent.system_prompt}, *messages]
        resp = await app.state.llm.chat(messages, model=agent.model, temperature=agent.temperature)
    else:
        resp = await app.state.llm.chat(messages, model=name)
    return resp.content or ""
