"""Memory service: RAG context for agents, interaction recording, self-reflection, feedback."""

import asyncio
import logging

from app.llm.base import LLMClient
from app.llm.types import ChatMessage, LLMError
from app.memory.embedder import Embedder, Vector
from app.memory.store import MemoryStore

log = logging.getLogger(__name__)

REFLECT_SYSTEM = (
    "You review finished work of an AI agent and extract reusable lessons. "
    "A lesson is a short, general, actionable rule (max 2 sentences) that would help the "
    "agent do similar tasks better next time. If there is nothing worth remembering, reply "
    "exactly NONE."
)


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder,
        llm: LLMClient | None = None,
        reflect: bool = True,
        reflect_model: str | None = None,
        top_k: int = 3,
        min_rating: int = 4,
        min_score: float = 0.35,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.reflect = reflect and llm is not None
        self.reflect_model = reflect_model
        self.top_k = top_k
        self.min_rating = min_rating
        self.min_score = min_score
        self._background: set[asyncio.Task[None]] = set()

    async def _embed(self, text: str) -> Vector | None:
        try:
            return (await self.embedder.embed([text[:8000]]))[0]
        except (LLMError, IndexError) as exc:
            log.warning("embedding failed: %s", exc)
            return None

    async def context(self, agent: str, query: str) -> str:
        parts = []
        rules = await asyncio.to_thread(self.store.owner_rules, agent)
        if rules:
            parts.append(
                "## Owner rules (always follow)\n" + "\n".join(f"- {r.text}" for r in rules)
            )
        vec = await self._embed(query)
        if vec is None:
            return "\n\n".join(parts)
        knowledge = await asyncio.to_thread(
            self.store.search_knowledge, vec, self.top_k, self.min_score
        )
        lessons = await asyncio.to_thread(
            self.store.search_lessons, agent, vec, self.top_k, self.min_score
        )
        examples = await asyncio.to_thread(
            self.store.search_interactions, agent, vec, self.top_k, self.min_score,
            self.min_rating,
        )  # fmt: skip
        if knowledge:
            kb = "\n\n".join(f"[{c.title}] {c.text}" for _, c in knowledge)
            parts.append("## Relevant company knowledge\n" + kb)
        if lessons:
            parts.append(
                "## Lessons learned from past work\n"
                + "\n".join(f"- {les.text}" for _, les in lessons)
            )
        if examples:
            shots = "\n\n".join(f"Q: {i.prompt[:600]}\nA: {i.answer[:1200]}" for _, i in examples)
            parts.append("## Similar past tasks with answers the owner rated well\n" + shots)
        return "\n\n".join(parts)

    async def record(
        self, agent: str, client: str, messages: list[ChatMessage], answer: str
    ) -> int | None:
        prompt = next(
            (m["content"] for m in reversed(messages)
             if m.get("role") == "user" and isinstance(m.get("content"), str)),
            "",
        )  # fmt: skip
        if not prompt:
            return None
        vec = await self._embed(prompt)
        interaction_id = await asyncio.to_thread(
            self.store.add_interaction, client, agent, prompt, answer, vec
        )
        if self.reflect and answer:
            task = asyncio.create_task(self._reflect(agent, prompt, answer, interaction_id))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        return interaction_id

    async def _reflect(self, agent: str, prompt: str, answer: str, interaction_id: int) -> None:
        assert self.llm is not None
        try:
            resp = await self.llm.chat(
                [
                    {"role": "system", "content": REFLECT_SYSTEM},
                    {
                        "role": "user",
                        "content": f"Task:\n{prompt[:2000]}\n\nResult:\n{answer[:4000]}",
                    },
                ],
                model=self.reflect_model,
                temperature=0.2,
            )
        except LLMError as exc:
            log.warning("reflection failed: %s", exc)
            return
        text = (resp.content or "").strip()
        if not text or text.upper().startswith("NONE") or len(text) > 600:
            return
        await self.add_lesson(agent, text, "reflection", interaction_id)

    async def add_lesson(
        self, agent: str, text: str, source: str, interaction_id: int | None = None
    ) -> int:
        vec = await self._embed(text)
        return await asyncio.to_thread(
            self.store.add_lesson, agent, text, source, vec, interaction_id
        )

    async def ingest(self, title: str, text: str, max_chars: int = 900) -> dict:
        """Chunk a document, embed each chunk and store it as searchable company knowledge."""
        import uuid

        doc_id = uuid.uuid4().hex[:12]
        chunks = chunk_text(text, max_chars)
        for i, chunk in enumerate(chunks):
            vec = await self._embed(chunk)
            await asyncio.to_thread(self.store.add_knowledge_chunk, doc_id, title, i, chunk, vec)
        return {"doc_id": doc_id, "title": title, "chunks": len(chunks)}

    async def feedback(self, interaction_id: int, rating: int, comment: str | None) -> bool:
        """Owner rating. A low rating with a comment becomes a lesson for that agent."""
        interaction = await asyncio.to_thread(self.store.get_interaction, interaction_id)
        if interaction is None:
            return False
        await asyncio.to_thread(self.store.rate, interaction_id, rating, comment)
        if comment and rating <= 2:
            await self.add_lesson(
                interaction.agent,
                f"Owner correction on a past task ({interaction.prompt[:120]!r}): {comment}",
                "feedback",
                interaction_id,
            )
        return True

    async def drain(self) -> None:
        """Wait for pending reflections (shutdown/tests)."""
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    """Split text into chunks on blank lines, keeping each under ~max_chars."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paras:
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            # a single huge paragraph is hard-split
            while len(para) > max_chars:
                chunks.append(para[:max_chars])
                para = para[max_chars:]
            current = para
    if current:
        chunks.append(current)
    return chunks or ([text.strip()] if text.strip() else [])
