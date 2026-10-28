import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.api.keys import KEY_PREFIX, KeyStore
from app.config import Settings
from app.llm.mock import MockLLM, tool_reply
from app.llm.registry import ModelRegistry, load_config
from app.llm.types import LLMUnavailable
from app.main import create_app

ADMIN = "admin-secret-value"
YAML = """
backends: {gpu: {base_url: "http://gpu/v1"}}
default: general
models:
  general: {backend: gpu, model: qwen}
  coder: {backend: gpu, model: coder}
"""


def test_keystore_lifecycle(tmp_path: Path) -> None:
    store = KeyStore(tmp_path / "k.db")
    key, rec = store.create("bot")
    assert key.startswith(KEY_PREFIX) and rec.label == "bot" and rec.active
    assert key not in (tmp_path / "k.db").read_bytes().decode("latin-1")  # only hash stored
    assert store.verify(key).id == rec.id
    assert store.get(rec.id).last_used_at is not None
    assert store.verify(key + "x") is None
    assert store.verify("garbage") is None
    assert store.revoke(rec.id) and not store.revoke(rec.id)
    assert store.verify(key) is None
    assert not store.list()[0].active


@pytest.fixture
def llm(tmp_path: Path) -> MockLLM:
    return MockLLM(["hello"])


@pytest.fixture
def client(tmp_path: Path, llm: MockLLM) -> Iterator[TestClient]:
    cfg = tmp_path / "models.yaml"
    cfg.write_text(YAML)
    registry = ModelRegistry(load_config(cfg, {}), env={}, client_factory=lambda b, k: llm)
    settings = Settings(_env_file=None, data_dir=str(tmp_path), admin_api_key=ADMIN)
    with TestClient(create_app(settings, llm=registry)) as c:
        yield c


@pytest.fixture
def key(client: TestClient) -> str:
    return client.app.state.keys.create("test-app")[0]


def auth(k: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {k}"}


MSG = {"messages": [{"role": "user", "content": "hi"}]}


def test_requires_key(client: TestClient) -> None:
    assert client.post("/v1/chat/completions", json=MSG).status_code == 401
    r = client.post("/v1/chat/completions", json=MSG, headers=auth("sk-dev-wrong"))
    assert r.status_code == 401


def test_chat_completion(client: TestClient, key: str, llm: MockLLM) -> None:
    r = client.post(
        "/v1/chat/completions",
        json={**MSG, "model": "coder", "temperature": 0.1},
        headers=auth(key),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "coder"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "hello"}
    assert llm.calls[-1]["model"] == "coder" and llm.calls[-1]["temperature"] == 0.1


def test_default_model_and_admin_key(client: TestClient, llm: MockLLM) -> None:
    r = client.post("/v1/chat/completions", json=MSG, headers=auth(ADMIN))
    assert r.status_code == 200 and r.json()["model"] == "general"
    assert llm.calls[-1]["model"] == "qwen"


def test_tool_calls_passthrough(client: TestClient, key: str, llm: MockLLM) -> None:
    llm._replies[:] = [tool_reply("shell", '{"cmd":"ls"}')]
    r = client.post("/v1/chat/completions", json=MSG, headers=auth(key))
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "shell"


def test_streaming(client: TestClient, key: str) -> None:
    r = client.post("/v1/chat/completions", json={**MSG, "stream": True}, headers=auth(key))
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    first = json.loads(events[0])
    assert first["object"] == "chat.completion.chunk"
    assert first["choices"][0]["delta"]["content"] == "hello"


def test_errors(client: TestClient, key: str, llm: MockLLM) -> None:
    r = client.post("/v1/chat/completions", json={**MSG, "model": "nope"}, headers=auth(key))
    assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_found"
    llm._replies[:] = [LLMUnavailable("down")]
    r = client.post("/v1/chat/completions", json=MSG, headers=auth(key))
    assert r.status_code == 503
    r = client.post("/v1/chat/completions", json={"messages": []}, headers=auth(key))
    assert r.status_code == 422


def test_models_and_admin_usage(client: TestClient, key: str) -> None:
    ids = [m["id"] for m in client.get("/v1/models", headers=auth(key)).json()["data"]]
    assert ids == ["general", "coder"]
    assert client.get("/v1/admin/usage", headers=auth(key)).status_code == 403
    client.post("/v1/chat/completions", json=MSG, headers=auth(key))
    usage = client.get("/v1/admin/usage", headers=auth(ADMIN)).json()
    assert usage["general"]["requests"] == 1


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "cli.db")
    assert cli.main(["secret"]) == 0
    assert len(capsys.readouterr().out.strip()) >= 40
    assert cli.main(["--db", db, "keys", "create", "my-bot"]) == 0
    key = capsys.readouterr().out.splitlines()[1]
    assert KeyStore(db).verify(key) is not None
    assert cli.main(["--db", db, "keys", "list"]) == 0
    assert "my-bot" in capsys.readouterr().out
    assert cli.main(["--db", db, "keys", "revoke", "1"]) == 0
    assert cli.main(["--db", db, "keys", "revoke", "1"]) == 1
