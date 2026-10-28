"""Model registry: named backends + model aliases with fallback chains (config/models.yaml)."""

import logging
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from app.llm.base import LLMClient
from app.llm.openai_compat import OpenAICompatClient
from app.llm.rotating import RotatingKeyClient
from app.llm.types import ChatMessage, LLMResponse, LLMUnavailable, ToolSchema
from app.llm.usage import UsageMeter

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackendConfig:
    name: str
    base_url: str
    api_key_env: str = ""
    keys_env: str = ""  # env var holding comma-separated keys -> rotate across them
    timeout: float = 120.0


@dataclass(frozen=True)
class ModelAlias:
    name: str
    backend: str
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    fallback: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegistryConfig:
    backends: dict[str, BackendConfig]
    models: dict[str, ModelAlias]
    default: str


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> RegistryConfig:
    """Parse models.yaml. `${VAR}` in base_url is expanded from `env` (default: os.environ)."""
    env = os.environ if env is None else env
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text()) or {}
    backends = {}
    for name, b in (raw.get("backends") or {}).items():
        backends[name] = BackendConfig(
            name=name,
            base_url=_expand(b["base_url"], env),
            api_key_env=b.get("api_key_env", ""),
            keys_env=b.get("keys_env", ""),
            timeout=float(b.get("timeout", 120.0)),
        )
    models = {
        name: ModelAlias(
            name=name,
            backend=m["backend"],
            model=m["model"],
            temperature=m.get("temperature"),
            max_tokens=m.get("max_tokens"),
            fallback=list(m.get("fallback") or []),
        )
        for name, m in (raw.get("models") or {}).items()
    }
    cfg = RegistryConfig(backends=backends, models=models, default=raw.get("default", ""))
    _validate(cfg)
    return cfg


_VAR = re.compile(r"\$\{(\w+)\}")


def _expand(value: str, env: Mapping[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        if m.group(1) not in env:
            raise ValueError(f"environment variable {m.group(1)} is not set")
        return env[m.group(1)]

    return _VAR.sub(sub, value)


def _validate(cfg: RegistryConfig) -> None:
    if cfg.default not in cfg.models:
        raise ValueError(f"default model alias {cfg.default!r} is not defined")
    for alias in cfg.models.values():
        if alias.backend not in cfg.backends:
            raise ValueError(f"model {alias.name!r} uses unknown backend {alias.backend!r}")
        for fb in alias.fallback:
            if fb not in cfg.models:
                raise ValueError(f"model {alias.name!r} has unknown fallback {fb!r}")


ClientFactory = Callable[[BackendConfig, str], LLMClient]


def _default_factory(backend: BackendConfig, api_key: str) -> LLMClient:
    return OpenAICompatClient(
        base_url=backend.base_url, default_model="", api_key=api_key, timeout=backend.timeout
    )


class ModelRegistry:
    """Resolves aliases to backends and implements LLMClient with alias-level fallback."""

    def __init__(
        self,
        config: RegistryConfig,
        env: Mapping[str, str] | None = None,
        client_factory: ClientFactory = _default_factory,
        usage: UsageMeter | None = None,
    ) -> None:
        env = os.environ if env is None else env
        self.config = config
        self.usage = usage or UsageMeter()
        self._clients: dict[str, LLMClient] = {
            name: self._build_client(b, env, client_factory) for name, b in config.backends.items()
        }

    @staticmethod
    def _build_client(
        backend: BackendConfig, env: Mapping[str, str], factory: ClientFactory
    ) -> LLMClient:
        if backend.keys_env:
            keys = [k.strip() for k in env.get(backend.keys_env, "").split(",") if k.strip()]
            if keys:
                return RotatingKeyClient([factory(backend, k) for k in keys])
            log.warning(
                "backend %s: %s is empty; no keys to rotate", backend.name, backend.keys_env
            )
        api_key = env.get(backend.api_key_env, "") if backend.api_key_env else ""
        return factory(backend, api_key)

    def aliases(self) -> list[str]:
        return list(self.config.models)

    def chain(self, alias: str) -> list[ModelAlias]:
        """Alias followed by its fallbacks (breadth-first, no repeats)."""
        if alias not in self.config.models:
            raise KeyError(f"unknown model alias {alias!r}")
        order: list[str] = []
        queue = [alias]
        while queue:
            name = queue.pop(0)
            if name in order:
                continue
            order.append(name)
            queue.extend(self.config.models[name].fallback)
        return [self.config.models[n] for n in order]

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        tools: list[ToolSchema] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        alias_name = model or self.config.default
        last_exc: LLMUnavailable | None = None
        for alias in self.chain(alias_name):
            client = self._clients[alias.backend]
            start = time.monotonic()
            try:
                resp = await client.chat(
                    messages,
                    model=alias.model,
                    tools=tools,
                    temperature=temperature if temperature is not None else alias.temperature,
                    max_tokens=max_tokens if max_tokens is not None else alias.max_tokens,
                )
            except LLMUnavailable as exc:
                self.usage.record_error(alias.name)
                log.warning("alias %s unavailable (%s), trying fallback", alias.name, exc)
                last_exc = exc
                continue
            self.usage.record(
                alias.name,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
                time.monotonic() - start,
            )
            return resp
        assert last_exc is not None
        raise last_exc

    def current_model(self, alias: str) -> str:
        return self.config.models[alias].model

    def set_model(self, alias: str, model: str) -> None:
        """Point an alias at another backend model (e.g. a fine-tuned version), at runtime."""
        if alias not in self.config.models:
            raise KeyError(alias)
        self.config.models[alias] = replace(self.config.models[alias], model=model)
        log.info("alias %s now uses model %s", alias, model)

    async def chat_direct(
        self, alias: str, model: str, messages: list[ChatMessage], **kwargs: Any
    ) -> LLMResponse:
        """Call a specific backend model on the alias's backend, bypassing fallback."""
        backend = self.config.models[alias].backend
        return await self._clients[backend].chat(messages, model=model, **kwargs)

    async def aclose(self) -> None:
        for client in self._clients.values():
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()
