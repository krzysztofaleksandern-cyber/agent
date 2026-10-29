"""Learning cycle glue: dataset export, candidate evaluation, promotion, rollback."""

import asyncio
import logging
from typing import Any

from app.agents.profiles import AgentRegistry
from app.learning.dataset import build_examples, to_jsonl
from app.learning.evaluate import EvalCase, run_eval
from app.learning.versions import VersionStore
from app.llm.registry import ModelRegistry
from app.memory.store import MemoryStore

log = logging.getLogger(__name__)


class LearningPipeline:
    def __init__(
        self,
        registry: ModelRegistry,
        versions: VersionStore,
        memory: MemoryStore,
        agents: AgentRegistry,
        cases: dict[str, list[EvalCase]],
        min_score: float = 0.5,
        margin: float = 0.0,
    ) -> None:
        self.registry = registry
        self.versions = versions
        self.memory = memory
        self.agents = agents
        self.cases = cases
        self.min_score = min_score
        self.margin = margin
        self._base_models = {a: registry.current_model(a) for a in registry.aliases()}

    def apply_active(self) -> None:
        """On startup: point aliases at their active fine-tuned versions."""
        for alias, version in self.versions.active().items():
            if alias in self._base_models:
                self.registry.set_model(alias, version.model)

    def dataset(self, min_rating: int = 4, agent: str | None = None) -> str:
        prompts = {a.name: a.system_prompt for a in self.agents.all()}
        rows = self.memory.rated(min_rating, agent)
        return to_jsonl(build_examples(rows, prompts))

    async def evaluate_candidate(self, alias: str, model: str, note: str | None = None) -> dict:
        if alias not in self._base_models:
            raise KeyError(alias)
        cases = self.cases.get(alias) or []
        if not cases:
            raise ValueError(f"no eval cases for alias {alias!r} (config/eval.yaml)")
        current = self.registry.current_model(alias)
        version_id = await asyncio.to_thread(
            self.versions.add, alias, model, self._base_models[alias], note
        )

        def chat_with(m: str):
            return lambda msgs: self.registry.chat_direct(alias, m, msgs, temperature=0.0)

        new_score, new_results = await run_eval(chat_with(model), cases)
        old_score, old_results = await run_eval(chat_with(current), cases)
        await asyncio.to_thread(self.versions.set_scores, version_id, new_score, old_score)
        promoted = new_score >= self.min_score and new_score >= old_score + self.margin
        if promoted:
            await asyncio.to_thread(self.versions.activate, version_id)
            self.registry.set_model(alias, model)
        else:
            await asyncio.to_thread(self.versions.reject, version_id)
        log.info(
            "candidate %s for %s: %.2f vs %.2f -> %s",
            model, alias, new_score, old_score, "promoted" if promoted else "rejected",
        )  # fmt: skip
        return {
            "version_id": version_id,
            "alias": alias,
            "candidate": model,
            "previous": current,
            "score": new_score,
            "baseline_score": old_score,
            "promoted": promoted,
            "cases": [
                {"prompt": c.prompt[:80], "candidate": n, "baseline": o}
                for c, n, o in zip(cases, new_results, old_results, strict=True)
            ],
        }

    async def rollback(self, alias: str) -> dict[str, Any]:
        if alias not in self._base_models:
            raise KeyError(alias)
        now = await asyncio.to_thread(self.versions.rollback, alias)
        model = now.model if now else self._base_models[alias]
        self.registry.set_model(alias, model)
        return {"alias": alias, "model": model}
