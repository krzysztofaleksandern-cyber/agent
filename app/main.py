"""FastAPI application factory and dependency wiring."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI

from app.agent.loop import AgentRunner
from app.agents.profiles import AgentRegistry
from app.api.approvals_routes import router as approvals_router
from app.api.console_routes import router as console_router
from app.api.jobs_routes import router as jobs_router
from app.api.keys import KeyStore
from app.api.learning_routes import router as learning_router
from app.api.memory_routes import router as memory_router
from app.api.operator_routes import router as operator_router
from app.api.routes import router as api_router
from app.api.tasks_routes import router as tasks_router
from app.approvals.gate import ApprovalGate
from app.audit.log import AuditLog
from app.config import Settings, get_settings
from app.console.manager import ConsoleManager
from app.control import ControlState
from app.learning.evaluate import load_cases
from app.learning.pipeline import LearningPipeline
from app.learning.versions import VersionStore
from app.llm.base import LLMClient
from app.llm.registry import ModelRegistry, load_config
from app.logging import setup_logging
from app.memory.embedder import Embedder, HashEmbedder, OpenAICompatEmbedder
from app.memory.service import MemoryService
from app.memory.store import MemoryStore
from app.operator.hub import OperatorHub
from app.sandbox.runner import DockerSandbox, LocalRunner, SandboxRunner
from app.scheduler.jobs import Job, JobStore
from app.scheduler.runner import SchedulerLoop
from app.tasks.store import Task, TaskStore
from app.tasks.webhook import WebhookSender
from app.tasks.worker import Worker

log = logging.getLogger(__name__)


def _app_version() -> str:
    try:
        return version("devagent")
    except PackageNotFoundError:
        return "0.0.0"


def _make_sandbox(settings: Settings) -> SandboxRunner:
    if settings.sandbox_backend == "local":
        log.warning("SANDBOX_BACKEND=local: agent commands run WITHOUT isolation")
        return LocalRunner(settings.sandbox_timeout, settings.sandbox_max_output)
    return DockerSandbox(
        image=settings.sandbox_image,
        cpus=settings.sandbox_cpus,
        memory=settings.sandbox_memory,
        pids_limit=settings.sandbox_pids_limit,
        timeout_s=settings.sandbox_timeout,
        max_output=settings.sandbox_max_output,
    )


def _make_embedder(settings: Settings) -> Embedder:
    if settings.memory_embedder == "hash":
        return HashEmbedder()
    return OpenAICompatEmbedder(settings.ollama_url.rstrip("/") + "/v1", settings.embed_model)


def _load_eval_cases(path: str) -> dict:
    return load_cases(path) if Path(path).exists() else {}


def _make_services(settings: Settings) -> dict:
    from app.connectors.calendar import CalendarStore
    from app.connectors.crm import CrmStore
    from app.connectors.invoicing import InvoiceStore

    services: dict = {
        "calendar": CalendarStore(settings.db_path),
        "crm": CrmStore(settings.db_path),
        "invoices": InvoiceStore(settings.db_path, settings.company_seller),
    }
    if settings.email_enabled:
        from app.connectors.email import EmailConfig, ImapSmtpMailbox

        services["mailbox"] = ImapSmtpMailbox(
            EmailConfig(
                imap_host=settings.email_imap_host,
                smtp_host=settings.email_smtp_host or settings.email_imap_host,
                username=settings.email_username,
                password=settings.email_password.get_secret_value(),
                from_addr=settings.email_from or settings.email_username,
                imap_port=settings.email_imap_port,
                smtp_port=settings.email_smtp_port,
            )
        )
    return services


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    sandbox: SandboxRunner | None = None,
) -> FastAPI:
    """`llm` / `sandbox` override the real components (tests). `llm` must expose the
    registry interface (aliases, config, usage)."""
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

        async def notify_approval(payload: dict) -> None:
            if settings.approval_webhook_url:
                await app.state.webhooks.send(
                    settings.approval_webhook_url, "approval.requested", payload
                )

        app.state.approvals = ApprovalGate(
            settings.approval_timeout, notify_approval, settings.approval_mode
        )
        app.state.memory = MemoryService(
            MemoryStore(settings.db_path),
            _make_embedder(settings),
            app.state.llm,
            reflect=settings.memory_reflect,
            top_k=settings.memory_top_k,
            min_rating=settings.memory_min_rating,
        )
        app.state.learning = LearningPipeline(
            app.state.llm,
            VersionStore(settings.db_path),
            app.state.memory.store,
            app.state.agents,
            _load_eval_cases(settings.eval_config),
            min_score=settings.learning_min_score,
        )
        app.state.learning.apply_active()
        app.state.operator = OperatorHub(dispatch_timeout=settings.operator_dispatch_timeout)
        app.state.audit = AuditLog(settings.db_path)
        app.state.control = ControlState()
        app.state.console = ConsoleManager(
            settings.db_path, settings.console_otp_ttl, settings.console_session_ttl
        )
        app.state.runner = AgentRunner(
            app.state.llm,
            app.state.agents,
            sandbox or _make_sandbox(settings),
            settings.workspaces_dir,
            http_allowlist=settings.http_allowlist_list,
            approver=app.state.approvals,
            memory=app.state.memory,
            operator_hub=app.state.operator,
            services=_make_services(settings),
            audit=app.state.audit,
            control=app.state.control,
        )

        async def run_task(task: Task) -> str:
            if app.state.agents.get(task.agent) is None:  # plain model alias
                resp = await app.state.llm.chat(task.messages, model=task.agent)
                return resp.content or ""
            result = await app.state.runner.run(task.agent, task.messages, client=task.client)
            return result.content

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
        app.state.jobs = JobStore(settings.db_path)

        async def enqueue_job(job: Job) -> None:
            await asyncio.to_thread(
                app.state.tasks.create,
                "scheduler",
                job.agent,
                [{"role": "user", "content": job.prompt}],
                None,
                settings.task_max_attempts,
            )
            app.state.worker.wake()
            log.info("scheduled job %s -> task for agent %s", job.id, job.agent)

        app.state.scheduler = SchedulerLoop(app.state.jobs, enqueue_job)
        app.state.scheduler.start()
        yield
        await app.state.scheduler.stop()
        app.state.jobs.close()
        await app.state.worker.stop()
        await app.state.memory.drain()
        app.state.memory.store.close()
        app.state.learning.versions.close()
        embedder_close = getattr(app.state.memory.embedder, "aclose", None)
        if embedder_close is not None:
            await embedder_close()
        app.state.tasks.close()
        await app.state.webhooks.aclose()
        app.state.llm.usage.save(usage_path)
        services_cal = app.state.runner.services.get("calendar")
        if services_cal is not None:
            services_cal.close()
        app.state.console.close()
        app.state.audit.close()
        app.state.keys.close()
        if llm is None:
            await app.state.llm.aclose()
        log.info("shutting down")

    app = FastAPI(title="devagent", version=_app_version(), lifespan=lifespan)
    app.state.settings = settings
    app.include_router(api_router)
    app.include_router(tasks_router)
    app.include_router(approvals_router)
    app.include_router(memory_router)
    app.include_router(learning_router)
    app.include_router(jobs_router)
    app.include_router(operator_router)
    app.include_router(console_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app
