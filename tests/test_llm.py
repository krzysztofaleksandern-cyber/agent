import json
from pathlib import Path

import httpx
import pytest

from app.llm.mock import MockLLM, tool_reply
from app.llm.ollama_admin import OllamaAdmin
from app.llm.openai_compat import OpenAICompatClient
from app.llm.registry import ModelRegistry, load_config
from app.llm.types import LLMBadResponse, LLMResponse, LLMTimeout, LLMUnavailable

COMPLETION = {
    "model": "qwen2.5:14b",
    "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
}


def make_client(handler, **kw) -> OpenAICompatClient:
    return OpenAICompatClient(
        "http://llm/v1", "m", transport=httpx.MockTransport(handler), backoff=0, **kw
    )


async def test_chat_success_and_payload() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=COMPLETION)

    client = make_client(handler, api_key="k")
    resp = await client.chat([{"role": "user", "content": "x"}], temperature=0.1, tools=[{"t": 1}])
    assert resp.content == "hi"
    assert resp.usage.total_tokens == 7
    assert seen["url"] == "http://llm/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "m"
    assert seen["body"]["temperature"] == 0.1
    assert seen["body"]["tools"] == [{"t": 1}]


async def test_tool_calls_parsed() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "read_file", "arguments": '{"p":1}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    client = make_client(lambda r: httpx.Response(200, json=body))
    resp = await client.chat([])
    assert resp.tool_calls[0].name == "read_file"
    assert resp.to_message()["tool_calls"][0]["function"]["arguments"] == '{"p":1}'


async def test_retry_then_success() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=COMPLETION)

    resp = await make_client(handler, max_retries=2).chat([])
    assert resp.content == "hi" and len(calls) == 3


async def test_retries_exhausted() -> None:
    with pytest.raises(LLMUnavailable):
        await make_client(lambda r: httpx.Response(429), max_retries=1).chat([])


async def test_timeout_and_connect_errors() -> None:
    def timeout(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    def refused(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    with pytest.raises(LLMTimeout):
        await make_client(timeout, max_retries=0).chat([])
    with pytest.raises(LLMUnavailable):
        await make_client(refused, max_retries=0).chat([])


async def test_bad_request_not_retried() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, text="bad")

    with pytest.raises(LLMBadResponse):
        await make_client(handler).chat([])
    assert len(calls) == 1
    with pytest.raises(LLMBadResponse):
        await make_client(lambda r: httpx.Response(200, json={"x": 1})).chat([])


async def test_mock_llm_script() -> None:
    llm = MockLLM([tool_reply("shell", '{"cmd":"ls"}'), "done"])
    first = await llm.chat([{"role": "user", "content": "go"}])
    second = await llm.chat([])
    third = await llm.chat([])
    assert first.tool_calls[0].name == "shell"
    assert second.content == third.content == "done"
    assert len(llm.calls) == 3


YAML = """
backends:
  a: {base_url: "${URL}/v1"}
  b: {base_url: "http://b/v1", api_key_env: B_KEY}
default: main
models:
  main: {backend: a, model: big, temperature: 0.3, fallback: [backup]}
  backup: {backend: b, model: small, fallback: [main]}
"""


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    p = tmp_path / "models.yaml"
    p.write_text(YAML)
    return p


def test_load_config(cfg_path: Path) -> None:
    cfg = load_config(cfg_path, {"URL": "http://gpu:11434"})
    assert cfg.backends["a"].base_url == "http://gpu:11434/v1"
    assert cfg.models["main"].fallback == ["backup"]
    with pytest.raises(ValueError, match="URL"):
        load_config(cfg_path, {})


@pytest.mark.parametrize(
    "bad",
    [
        "backends: {a: {base_url: x}}\ndefault: nope\nmodels: {}",
        "backends: {}\ndefault: m\nmodels: {m: {backend: zz, model: x}}",
        "backends: {a: {base_url: x}}\ndefault: m\n"
        "models: {m: {backend: a, model: x, fallback: [q]}}",
    ],
)
def test_invalid_config(tmp_path: Path, bad: str) -> None:
    p = tmp_path / "m.yaml"
    p.write_text(bad)
    with pytest.raises(ValueError):
        load_config(p, {})


def test_repo_models_yaml_is_valid() -> None:
    cfg = load_config(
        Path(__file__).parent.parent / "config/models.yaml", {"OLLAMA_URL": "http://x"}
    )
    assert cfg.default in cfg.models


async def test_registry_fallback_and_usage(cfg_path: Path) -> None:
    mocks = {"a": MockLLM([LLMUnavailable("down")]), "b": MockLLM(["from backup"])}
    keys = {}

    def factory(backend, api_key):
        keys[backend.name] = api_key
        return mocks[backend.name]

    reg = ModelRegistry(
        load_config(cfg_path, {"URL": "http://x"}), env={"B_KEY": "secret"}, client_factory=factory
    )
    resp = await reg.chat([{"role": "user", "content": "q"}])
    assert resp.content == "from backup"
    assert keys == {"a": "", "b": "secret"}
    assert mocks["a"].calls[0]["model"] == "big"
    assert mocks["b"].calls[0]["model"] == "small"
    assert [a.name for a in reg.chain("backup")] == ["backup", "main"]
    usage = reg.usage.snapshot()
    assert usage["main"]["errors"] == 1
    assert usage["backup"]["requests"] == 1
    with pytest.raises(KeyError):
        await reg.chat([], model="nope")


async def test_registry_all_down(cfg_path: Path) -> None:
    down = MockLLM([LLMUnavailable("x")])
    reg = ModelRegistry(
        load_config(cfg_path, {"URL": "u"}), env={}, client_factory=lambda b, k: down
    )
    with pytest.raises(LLMUnavailable):
        await reg.chat([])


async def test_registry_passes_alias_defaults(cfg_path: Path) -> None:
    llm = MockLLM([LLMResponse(content="x", model="big")])
    reg = ModelRegistry(
        load_config(cfg_path, {"URL": "u"}), env={}, client_factory=lambda b, k: llm
    )
    await reg.chat([])
    await reg.chat([], temperature=0.9, max_tokens=50)
    assert llm.calls[0]["temperature"] == 0.3
    assert llm.calls[1]["temperature"] == 0.9
    assert llm.calls[1]["max_tokens"] == 50


async def test_ollama_admin() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:14b", "size": 9}]})
        if req.url.path == "/api/pull":
            assert json.loads(req.content) == {"model": "llama3.1:8b", "stream": False}
            return httpx.Response(200, json={"status": "success"})
        return httpx.Response(200, json={"version": "0.5"})

    admin = OllamaAdmin("http://gpu:11434/v1", transport=httpx.MockTransport(handler))
    assert (await admin.list_models())[0].name == "qwen2.5:14b"
    assert await admin.pull("llama3.1:8b") == "success"
    assert await admin.is_up()

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=req)

    assert not await OllamaAdmin("http://gpu", transport=httpx.MockTransport(down)).is_up()
