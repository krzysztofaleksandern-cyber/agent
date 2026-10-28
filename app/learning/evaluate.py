"""Small regression eval: fixed prompts with simple checks, scored 0..1."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.llm.types import ChatMessage, LLMError, LLMResponse


@dataclass(frozen=True)
class EvalCase:
    prompt: str
    expect_any: list[str] = field(default_factory=list)  # case-insensitive substrings
    expect_regex: str | None = None
    forbid: list[str] = field(default_factory=list)

    def check(self, answer: str) -> bool:
        low = answer.lower()
        if self.expect_any and not any(e.lower() in low for e in self.expect_any):
            return False
        if self.expect_regex and not re.search(self.expect_regex, answer, re.S):
            return False
        return not any(f.lower() in low for f in self.forbid)


def load_cases(path: str | Path) -> dict[str, list[EvalCase]]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return {alias: [EvalCase(**c) for c in cases] for alias, cases in raw.items()}


ChatFn = Callable[[list[ChatMessage]], Awaitable[LLMResponse]]


async def run_eval(chat: ChatFn, cases: list[EvalCase]) -> tuple[float, list[bool]]:
    results = []
    for case in cases:
        try:
            resp = await chat([{"role": "user", "content": case.prompt}])
            results.append(case.check(resp.content or ""))
        except LLMError:
            results.append(False)
    score = sum(results) / len(results) if results else 0.0
    return score, results
