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


AGENTS_YAML = """
agents:
  helper:
    model: general
    system_prompt: You help.
    temperature: 0.5
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
    agents = tmp_path / "agents.yaml"
    agents.write_text(AGENTS_YAML)
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        admin_api_key=ADMIN,
        agents_config=str(agents),
        memory_embedder="hash",
        memory_reflect=False,
    )
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
    assert ids == ["helper", "general", "coder"]
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


def test_chat_with_agent_profile(client: TestClient, key: str, llm: MockLLM) -> None:
    r = client.post("/v1/chat/completions", json={**MSG, "model": "helper"}, headers=auth(key))
    assert r.status_code == 200 and r.json()["model"] == "helper"
    call = llm.calls[-1]
    assert call["messages"][0] == {"role": "system", "content": "You help."}
    assert call["model"] == "qwen" and call["temperature"] == 0.5


def test_admin_agents(client: TestClient, key: str, tmp_path: Path) -> None:
    assert client.get("/v1/admin/agents", headers=auth(key)).status_code == 403
    assert "helper" in client.get("/v1/admin/agents", headers=auth(ADMIN)).json()
    r = client.put("/v1/admin/agents/helper", json={"system_prompt": "New."}, headers=auth(ADMIN))
    assert r.json()["helper"]["system_prompt"] == "New."
    assert "New." in (tmp_path / "agents.yaml").read_text()
    r = client.put(
        "/v1/admin/agents/bot", json={"model": "coder", "system_prompt": "x"}, headers=auth(ADMIN)
    )
    assert r.status_code == 200
    r = client.put("/v1/admin/agents/helper", json={"model": "nope"}, headers=auth(ADMIN))
    assert r.status_code == 400
    r = client.put("/v1/admin/agents/new", json={"model": "coder"}, headers=auth(ADMIN))
    assert r.status_code == 400  # missing system_prompt


def test_tasks_api(client: TestClient, key: str) -> None:
    import time

    r = client.post("/v1/tasks", json={"agent": "helper", "input": "hi"}, headers=auth(key))
    assert r.status_code == 202
    task_id = r.json()["id"]
    for _ in range(300):
        task = client.get(f"/v1/tasks/{task_id}", headers=auth(key)).json()
        if task["status"] == "done":
            break
        time.sleep(0.01)
    assert task["status"] == "done" and task["result"] == "hello"
    assert [t["id"] for t in client.get("/v1/tasks", headers=auth(key)).json()] == [task_id]

    other = client.app.state.keys.create("other")[0]
    assert client.get(f"/v1/tasks/{task_id}", headers=auth(other)).status_code == 404
    assert client.get(f"/v1/tasks/{task_id}", headers=auth(ADMIN)).status_code == 200
    r = client.post(f"/v1/tasks/{task_id}/cancel", headers=auth(key))
    assert r.json()["cancelled"] is False

    bad = {"agent": "nope", "input": "x"}
    assert client.post("/v1/tasks", json=bad, headers=auth(key)).status_code == 404
    both = {"agent": "helper", "input": "x", "messages": [{"role": "user", "content": "y"}]}
    assert client.post("/v1/tasks", json=both, headers=auth(key)).status_code == 422


def test_approvals_api(client: TestClient, key: str) -> None:
    import threading

    gate = client.app.state.approvals
    gate.timeout_s = 5
    result = {}
    loop = client.portal  # run review inside the app's event loop

    def ask() -> None:
        result["v"] = loop.call(gate.review, "git", {"args": ["push"]}, "test-app")

    thread = threading.Thread(target=ask)
    thread.start()
    for _ in range(200):
        pending = client.get("/v1/approvals", headers=auth(ADMIN)).json()
        if pending:
            break
        threading.Event().wait(0.01)
    assert client.get("/v1/approvals", headers=auth(key)).status_code == 403
    pid = pending[0]["id"]
    assert (
        client.post(f"/v1/approvals/{pid}", json={"answer": "hmm"}, headers=auth(ADMIN)).status_code
        == 422
    )
    r = client.post(f"/v1/approvals/{pid}", json={"answer": "TAK"}, headers=auth(ADMIN))
    assert r.json() == {"id": pid, "approved": True}
    thread.join(5)
    assert result["v"] is None
    assert (
        client.post(f"/v1/approvals/{pid}", json={"approve": True}, headers=auth(ADMIN)).status_code
        == 404
    )


def test_feedback_and_lessons(client: TestClient, key: str) -> None:
    r = client.post("/v1/chat/completions", json={**MSG, "model": "helper"}, headers=auth(key))
    iid = r.json()["interaction_id"]
    assert r.headers["x-interaction-id"] == str(iid)
    other = client.app.state.keys.create("other")[0]
    fb = {"interaction_id": iid, "rating": 1, "comment": "Always answer in Polish."}
    assert client.post("/v1/feedback", json=fb, headers=auth(other)).status_code == 404
    assert client.post("/v1/feedback", json=fb, headers=auth(key)).status_code == 200
    lessons = client.get("/v1/admin/lessons?agent=helper", headers=auth(ADMIN)).json()
    assert lessons[0]["source"] == "feedback" and "Polish" in lessons[0]["text"]

    r = client.post(
        "/v1/admin/lessons", json={"agent": "helper", "text": "Be brief."}, headers=auth(ADMIN)
    )
    lesson_id = r.json()["id"]
    client.post("/v1/chat/completions", json={**MSG, "model": "helper"}, headers=auth(key))
    system = client.app.state.llm._clients["gpu"].calls[-1]["messages"][0]["content"]
    assert "## Owner rules" in system and "Be brief." in system
    assert client.delete(f"/v1/admin/lessons/{lesson_id}", headers=auth(ADMIN)).status_code == 200
    assert client.delete(f"/v1/admin/lessons/{lesson_id}", headers=auth(ADMIN)).status_code == 404
    bad = {"agent": "ghost", "text": "abc"}
    assert client.post("/v1/admin/lessons", json=bad, headers=auth(ADMIN)).status_code == 404


def test_learning_api(client: TestClient, key: str) -> None:
    r = client.post("/v1/chat/completions", json={**MSG, "model": "helper"}, headers=auth(key))
    client.post(
        "/v1/feedback",
        json={"interaction_id": r.json()["interaction_id"], "rating": 5},
        headers=auth(key),
    )
    assert client.get("/v1/admin/dataset", headers=auth(key)).status_code == 403
    lines = client.get("/v1/admin/dataset", headers=auth(ADMIN)).text.strip().splitlines()
    assert json.loads(lines[0])["messages"][-1] == {"role": "assistant", "content": "hello"}
    r = client.post(
        "/v1/admin/candidates", json={"alias": "nope", "model": "x"}, headers=auth(ADMIN)
    )
    assert r.status_code == 404
    assert client.get("/v1/admin/versions", headers=auth(ADMIN)).json() == []
    r = client.post("/v1/admin/versions/general/rollback", headers=auth(ADMIN))
    assert r.json() == {"alias": "general", "model": "qwen"}


def test_operator_worker_channel(client: TestClient, key: str) -> None:
    # worker auth: dedicated token, not a client key
    client.app.state.settings.operator_worker_token = __import__("pydantic").SecretStr("worker-tok")
    wtok = {"Authorization": "Bearer worker-tok"}
    assert client.post("/v1/operator/poll", headers=auth(key)).status_code == 401
    assert client.post("/v1/operator/poll", headers=wtok).json() == {"command": None}
    # status is admin-only and reports the worker came by
    st = client.get("/v1/operator/status", headers=auth(ADMIN)).json()
    assert st["online"] is True
    assert client.get("/v1/operator/status", headers=auth(key)).status_code == 403
    # unknown result id is simply not accepted
    r = client.post("/v1/operator/result", json={"id": "x", "ok": True}, headers=wtok)
    assert r.json() == {"accepted": False}


def test_console_pwa_flow(client: TestClient) -> None:
    # static entrypoint is public
    assert client.get("/console/").status_code == 200
    assert client.get("/console/manifest.webmanifest").status_code == 200
    # protected endpoints need a session
    assert client.get("/console/api/status").status_code == 401
    assert client.post("/console/api/login", json={"otp": "999999"}).status_code == 401
    # real OTP -> session -> operator command + approvals reachable
    otp, _ = client.app.state.console.create_otp()
    tok = client.post("/console/api/login", json={"otp": otp}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert client.get("/console/api/status", headers=h).json()["online"] is False
    r = client.post("/console/api/command", json={"text": "open notepad"}, headers=h)
    assert r.status_code == 202 and r.json()["agent"] == "operator"
    assert client.get("/console/api/approvals", headers=h).json() == []
    # logout invalidates the session
    assert client.post("/console/api/logout", headers=h).json() == {"ok": True}
    assert client.get("/console/api/status", headers=h).status_code == 401


def test_admin_audit_and_console_activity(client: TestClient, key: str) -> None:
    client.app.state.audit.record("operator", "console", "os_shell", "ls", True)
    assert client.get("/v1/admin/audit", headers=auth(key)).status_code == 403
    rows = client.get("/v1/admin/audit", headers=auth(ADMIN)).json()
    assert rows and rows[0]["tool"] == "os_shell" and rows[0]["ok"] is True
    # console session can see recent activity
    otp, _ = client.app.state.console.create_otp()
    tok = client.post("/console/api/login", json={"otp": otp}).json()["token"]
    act = client.get("/console/api/activity", headers={"Authorization": "Bearer " + tok})
    assert act.status_code == 200 and act.json()[0]["tool"] == "os_shell"
