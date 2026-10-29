"""Agent profiles loaded from config/agents.yaml."""

import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

KNOWN_TOOLS = {
    "shell",
    "read_file",
    "write_file",
    "list_dir",
    "git",
    "http_get",
    "delegate",
    # operator tools (executed on the owner's computer by the host worker)
    "screenshot",
    "mouse_move",
    "mouse_click",
    "mouse_scroll",
    "type_text",
    "key_press",
    "os_run",
    "os_shell",
    "os_read_file",
    "os_write_file",
    "os_list_dir",
    # connectors
    "email_list",
    "email_read",
    "email_send",
    "calendar_list",
    "calendar_create",
    "calendar_delete",
    "crm_add_contact",
    "crm_find_contact",
    "crm_add_deal",
    "crm_list_deals",
    "crm_set_stage",
    "make_document",
}


@dataclass(frozen=True)
class AgentProfile:
    name: str
    model: str
    system_prompt: str
    description: str = ""
    tools: list[str] = field(default_factory=list)
    temperature: float | None = None
    max_steps: int = 10
    delegates: list[str] = field(default_factory=list)
    native_tools: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("name")
        return data


_FIELDS = set(AgentProfile.__dataclass_fields__) - {"name"}


def _profile(name: str, raw: dict[str, Any]) -> AgentProfile:
    unknown = set(raw) - _FIELDS
    if unknown:
        raise ValueError(f"agent {name!r}: unknown fields {sorted(unknown)}")
    return AgentProfile(name=name, **raw)


def validate(profiles: dict[str, AgentProfile], model_aliases: Iterable[str]) -> None:
    aliases = set(model_aliases)
    for p in profiles.values():
        if p.model not in aliases:
            raise ValueError(f"agent {p.name!r} uses unknown model alias {p.model!r}")
        bad_tools = set(p.tools) - KNOWN_TOOLS
        if bad_tools:
            raise ValueError(f"agent {p.name!r} has unknown tools {sorted(bad_tools)}")
        for d in p.delegates:
            if d not in profiles or d == p.name:
                raise ValueError(f"agent {p.name!r} has invalid delegate {d!r}")
        if p.delegates and "delegate" not in p.tools:
            raise ValueError(f"agent {p.name!r} has delegates but no 'delegate' tool")
        if p.max_steps < 1:
            raise ValueError(f"agent {p.name!r}: max_steps must be >= 1")


class AgentRegistry:
    """Holds profiles; admin updates are validated and written back to the YAML file."""

    def __init__(self, path: str | Path, model_aliases: Iterable[str]) -> None:
        self.path = Path(path)
        self._aliases = list(model_aliases)
        self._lock = threading.Lock()
        raw = yaml.safe_load(self.path.read_text()) or {}
        self._profiles = {n: _profile(n, r or {}) for n, r in (raw.get("agents") or {}).items()}
        validate(self._profiles, self._aliases)

    def names(self) -> list[str]:
        return list(self._profiles)

    def get(self, name: str) -> AgentProfile | None:
        return self._profiles.get(name)

    def all(self) -> list[AgentProfile]:
        return list(self._profiles.values())

    def upsert(self, name: str, changes: dict[str, Any]) -> AgentProfile:
        with self._lock:
            current = self._profiles.get(name)
            if current is None:
                profile = _profile(name, changes)
            else:
                unknown = set(changes) - _FIELDS
                if unknown:
                    raise ValueError(f"unknown fields {sorted(unknown)}")
                profile = replace(current, **changes)
            candidate = {**self._profiles, name: profile}
            validate(candidate, self._aliases)
            self._profiles = candidate
            self._save()
            return profile

    def _save(self) -> None:
        data = {"agents": {n: p.to_dict() for n, p in self._profiles.items()}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        tmp.replace(self.path)
