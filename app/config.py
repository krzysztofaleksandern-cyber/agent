"""Application settings loaded from environment variables / `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "prod", "test"] = "dev"
    log_level: str = "INFO"
    data_dir: str = "./data"

    # Model layer
    models_config: str = "config/models.yaml"
    ollama_url: str = "http://localhost:11434"


@lru_cache
def get_settings() -> Settings:
    return Settings()
