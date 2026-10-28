import pytest

from app.llm.mock import MockLLM
from app.llm.registry import ModelRegistry, load_config
from app.llm.rotating import RotatingKeyClient
from app.llm.types import LLMResponse, LLMUnavailable


def reply(text: str) -> LLMResponse:
    return LLMResponse(content=text, model="gemini")


async def test_round_robin_across_keys() -> None:
    a, b, c = MockLLM([reply("a")]), MockLLM([reply("b")]), MockLLM([reply("c")])
    client = RotatingKeyClient([a, b, c])
    outs = [(await client.chat([])).content for _ in range(4)]
    assert outs == ["a", "b", "c", "a"]  # wraps around
    assert len(a.calls) == 2 and len(b.calls) == 1


async def test_skips_rate_limited_key() -> None:
    bad, good = MockLLM([LLMUnavailable("429")]), MockLLM([reply("ok")])
    client = RotatingKeyClient([bad, good], cooldown_s=100)
    assert (await client.chat([])).content == "ok"
    # bad key is on cooldown now -> next call goes straight to the good key
    assert (await client.chat([])).content == "ok"
    assert len(bad.calls) == 1 and len(good.calls) == 2


async def test_all_keys_exhausted() -> None:
    clients = [MockLLM([LLMUnavailable("429")]) for _ in range(3)]
    with pytest.raises(LLMUnavailable, match="all 3 keys exhausted"):
        await RotatingKeyClient(clients).chat([])


def test_requires_clients() -> None:
    with pytest.raises(ValueError, match="at least one"):
        RotatingKeyClient([])


async def test_registry_builds_rotating_backend() -> None:
    yaml = """
backends:
  gemini: {base_url: "http://g/v1", keys_env: GEMINI_API_KEYS}
default: g
models:
  g: {backend: gemini, model: gemini-2.5-flash}
"""
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "m.yaml"
    p.write_text(yaml)
    built: list[str] = []

    def factory(backend, api_key):
        built.append(api_key)
        return MockLLM([reply(api_key)])

    reg = ModelRegistry(
        load_config(p, {}), env={"GEMINI_API_KEYS": "k1, k2 ,k3"}, client_factory=factory
    )
    assert built == ["k1", "k2", "k3"]  # three keys -> three clients
    assert isinstance(reg._clients["gemini"], RotatingKeyClient)
    assert (await reg.chat([])).content == "k1"
    assert (await reg.chat([])).content == "k2"


def test_repo_models_yaml_has_gemini() -> None:
    from pathlib import Path

    cfg = load_config(
        Path(__file__).parent.parent / "config/models.yaml",
        {"OLLAMA_URL": "http://x", "GEMINI_API_KEYS": "k"},
    )
    assert "gemini-pro" in cfg.models and cfg.backends["gemini"].keys_env == "GEMINI_API_KEYS"
