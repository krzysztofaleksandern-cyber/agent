"""End-to-end: every agent answers over the real API with a real ModelRegistry
(only .chat is replaced by a mock). Catches the 'model not found' 404 caused by
get_tools() raising KeyError for tools missing from _all_tools()."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.agents.profiles import KNOWN_TOOLS
from app.config import Settings
from app.llm.registry import ModelRegistry, load_config
from app.llm.types import LLMResponse, ToolCall, Usage
from app.main import create_app
from app.tools.builtin import _all_tools

ADMIN = "adm-e2e"


def make_mock_chat():
    """A real-registry-compatible chat: calls one known tool, then finalizes."""

    async def chat(messages, *, model=None, tools=None, temperature=None, max_tokens=None):
        last = messages[-1] if messages else {}
        content = last.get("content")
        if last.get("role") == "tool" or (
            isinstance(content, str) and content.startswith("Result of")
        ):
            return LLMResponse(
                content="Gotowe.", model=model or "mock", finish_reason="stop", usage=Usage(1, 1)
            )
        names = {t["function"]["name"] for t in (tools or [])}
        for tool_name, args in (
            ("note_add", json.dumps({"text": "test"})),
            ("invoice_list", "{}"),
            ("business_report", "{}"),
        ):
            if tool_name in names:
                return LLMResponse(
                    content=None,
                    model=model or "mock",
                    tool_calls=[ToolCall("c1", tool_name, args)],
                    finish_reason="tool_calls",
                    usage=Usage(1, 1),
                )
        return LLMResponse(
            content="Odpowiedz.", model=model or "mock", finish_reason="stop", usage=Usage(1, 1)
        )

    return chat


@pytest.fixture
def app_client(tmp_path) -> Iterator[tuple[TestClient, object]]:
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        admin_api_key=ADMIN,
        memory_embedder="hash",
        memory_reflect=False,
        sandbox_backend="local",
    )
    env = {"OLLAMA_URL": "http://localhost"}
    registry = ModelRegistry(load_config(settings.models_config, env), env=env)
    registry.chat = make_mock_chat()  # only .chat replaced; aliases/config stay real
    app = create_app(settings, llm=registry)
    with TestClient(app) as client:
        yield client, app


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _chat(client: TestClient, model: str):
    return client.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "zrob to"}]},
        headers=auth(ADMIN),
    )


def test_known_tools_match_all_tools() -> None:
    assert set(_all_tools()) == KNOWN_TOOLS


def test_every_agent_returns_200(app_client) -> None:
    client, app = app_client
    for name in app.state.agents.names():
        r = _chat(client, name)
        assert r.status_code == 200, (name, r.status_code, r.text)


def test_tool_agents_execute_and_audit(app_client) -> None:
    client, app = app_client
    for agent in ("jarvis", "bookkeeper", "analyst"):
        assert _chat(client, agent).status_code == 200, agent
    done = {(e.tool, e.ok) for e in app.state.audit.recent(500)}
    assert ("note_add", True) in done
    assert ("invoice_list", True) in done
    assert ("business_report", True) in done


def test_unknown_model_is_404(app_client) -> None:
    client, _ = app_client
    r = _chat(client, "nie-ma-takiego")
    assert r.status_code == 404
