from pathlib import Path

import httpx
import pytest

from app.llm.mock import MockLLM
from app.llm.types import LLMUnavailable
from app.memory.embedder import HashEmbedder, OpenAICompatEmbedder, cosine
from app.memory.service import MemoryService
from app.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "m.db")


async def test_hash_embedder_similarity() -> None:
    e = HashEmbedder()
    a, b, c = await e.embed(["fix the login bug", "login bug fix please", "bake a cake"])
    assert cosine(a, b) > 0.6 > cosine(a, c)
    assert cosine([], a) == 0.0


async def test_openai_embedder() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]},
        )

    e = OpenAICompatEmbedder("http://gpu/v1", transport=httpx.MockTransport(handler))
    assert await e.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=req)

    with pytest.raises(LLMUnavailable):
        await OpenAICompatEmbedder("http://gpu/v1", transport=httpx.MockTransport(down)).embed(
            ["a"]
        )


async def test_record_rate_and_rag(store: MemoryStore) -> None:
    svc = MemoryService(store, HashEmbedder(), reflect=False, min_score=0.2)
    msgs = [{"role": "user", "content": "How do I fix the login bug in auth.py?"}]
    iid = await svc.record("codex", "app", msgs, "Check token expiry in auth.py.")
    assert await svc.context("codex", "login bug auth.py") == ""  # unrated -> not used
    assert await svc.feedback(iid, 5, None)
    ctx = await svc.context("codex", "login bug in auth.py")
    assert "Check token expiry" in ctx and "rated well" in ctx
    assert await svc.context("writer", "login bug in auth.py") == ""  # other agent
    assert not await svc.feedback(999, 5, None)


async def test_feedback_creates_lesson(store: MemoryStore) -> None:
    svc = MemoryService(store, HashEmbedder(), reflect=False, min_score=0.1)
    iid = await svc.record(
        "writer", "app", [{"role": "user", "content": "Write a German email"}], "x"
    )
    await svc.feedback(iid, 1, "Use formal Sie in German emails")
    assert store.lessons("writer")[0].source == "feedback"
    ctx = await svc.context("writer", "German email to a client")
    assert "formal Sie" in ctx


async def test_reflection(store: MemoryStore) -> None:
    llm = MockLLM(["Run the tests before reporting success."])
    svc = MemoryService(store, HashEmbedder(), llm=llm, reflect=True)
    await svc.record("codex", "app", [{"role": "user", "content": "add feature"}], "added")
    await svc.drain()
    assert store.lessons("codex")[0].text == "Run the tests before reporting success."
    assert llm.calls[0]["messages"][0]["role"] == "system"

    llm2 = MockLLM(["NONE"])
    svc2 = MemoryService(store, HashEmbedder(), llm=llm2, reflect=True)
    await svc2.record("writer", "app", [{"role": "user", "content": "hi"}], "hello")
    await svc2.drain()
    assert store.lessons("writer") == []


async def test_global_lessons_and_embedding_failure(store: MemoryStore) -> None:
    svc = MemoryService(store, HashEmbedder(), reflect=False, min_score=0.1)
    await svc.add_lesson("*", "Never commit secrets to git", "owner")
    ctx = await svc.context("codex", "unrelated question")
    assert "Owner rules" in ctx and "Never commit secrets" in ctx  # owner rules always apply

    class Broken:
        async def embed(self, texts):
            raise LLMUnavailable("down")

    broken = MemoryService(store, Broken(), reflect=False)
    assert "Never commit secrets" in await broken.context("codex", "anything")
    iid = await broken.record("codex", "c", [{"role": "user", "content": "q"}], "a")
    assert iid is not None  # still recorded, just without embedding
