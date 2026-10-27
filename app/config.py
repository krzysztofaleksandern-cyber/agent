"""Application settings loaded from environment variables / `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "prod", "test"] = "dev"
    log_level: str = "INFO"
    data_dir: str = "./data"

    # WhatsApp Cloud API (used from Phase 2)
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    owner_phone: str = ""

    # LLM (used from Phase 5)
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "local-model"
    llm_api_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
