"""Settings for snap2list."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Vision LLM: any OpenAI-compatible endpoint (your devagent platform or Ollama directly)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: SecretStr = SecretStr("")
    vision_model: str = "llama3.2-vision:11b"
    request_timeout: float = 120.0

    # Marketplace publishing (optional; without tokens the app returns a manual draft)
    allegro_token: SecretStr = SecretStr("")
    allegro_api_url: str = "https://api.allegro.pl"
    olx_token: SecretStr = SecretStr("")
    olx_api_url: str = "https://www.olx.pl/api"

    currency: str = "PLN"


@lru_cache
def get_settings() -> Settings:
    return Settings()
