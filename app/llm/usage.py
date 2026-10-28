"""Usage counters per model alias, persisted as JSON between restarts."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


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

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.snapshot()))

    def load(self, path: str | Path) -> None:
        p = Path(path)
        if p.exists():
            raw = json.loads(p.read_text())
            self._data = {alias: AliasUsage(**vals) for alias, vals in raw.items()}
