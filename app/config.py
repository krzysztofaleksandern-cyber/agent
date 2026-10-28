"""Application settings loaded from environment variables / `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "prod", "test"] = "dev"
    log_level: str = "INFO"
    data_dir: str = "./data"

    # Model layer
    models_config: str = "config/models.yaml"
    agents_config: str = "config/agents.yaml"
    ollama_url: str = "http://localhost:11434"

    # Public API: admin key (generate with `python -m app.cli secret`)
    admin_api_key: SecretStr = SecretStr("")

    # Background tasks
    webhook_secret: SecretStr = SecretStr("")
    worker_concurrency: int = 1
    task_max_attempts: int = 3
    task_retry_backoff: float = 5.0

    # Sandbox & tools ("local" = no isolation, development only)
    sandbox_backend: Literal["docker", "local"] = "docker"
    sandbox_image: str = "devagent-sandbox:latest"
    sandbox_cpus: float = 1.0
    sandbox_memory: str = "1g"
    sandbox_pids_limit: int = 256
    sandbox_timeout: float = 120.0
    sandbox_max_output: int = 20_000
    http_allowlist: str = (
        "stacklogic.pl,nexum-holding.at,nexum-holding.pl,pypi.org,docs.python.org,github.com"
    )

    @property
    def http_allowlist_list(self) -> list[str]:
        return [d.strip().lower() for d in self.http_allowlist.split(",") if d.strip()]

    @property
    def workspaces_dir(self) -> Path:
        return Path(self.data_dir) / "workspaces"

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / "devagent.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()
