"""In-memory usage counters per model alias (persisted from Phase 5)."""

from dataclasses import asdict, dataclass


@dataclass
class AliasUsage:
    requests: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_latency_s: float = 0.0


class UsageMeter:
    def __init__(self) -> None:
        self._data: dict[str, AliasUsage] = {}

    def _get(self, alias: str) -> AliasUsage:
        return self._data.setdefault(alias, AliasUsage())

    def record(self, alias: str, prompt: int, completion: int, latency_s: float) -> None:
        u = self._get(alias)
        u.requests += 1
        u.prompt_tokens += prompt
        u.completion_tokens += completion
        u.total_latency_s += latency_s

    def record_error(self, alias: str) -> None:
        self._get(alias).errors += 1

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {alias: asdict(u) for alias, u in self._data.items()}
