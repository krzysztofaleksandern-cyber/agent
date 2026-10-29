import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.logging import RedactingFilter, preview, redact
from app.main import create_app


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_URL", "http://gpu:11434")
    s = Settings(_env_file=None)
    assert s.ollama_url == "http://gpu:11434"


@pytest.mark.parametrize(
    "raw",
    [
        "Authorization: Bearer abc.def-123",
        "api_key=xyz987654",
        '{"token": "EAAGm0PX4ZCpsBAabcdef"}',
        "using sk-abcdefghijklmnop now",
    ],
)
def test_redact_masks_secrets(raw: str) -> None:
    out = redact(raw)
    assert "***" in out
    for secret in ("abc.def-123", "xyz987654", "EAAGm0PX4ZCpsBAabcdef", "sk-abcdefghijklmnop"):
        assert secret not in out


def test_preview_truncates() -> None:
    text = "word " * 100
    out = preview(text, limit=20)
    assert len(out) < 50
    assert "(500 chars)" in out
    assert preview("short") == "short"


def test_logging_filter_redacts() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "key: %s", ("token=abcdef123",), None)
    RedactingFilter().filter(record)
    assert "abcdef123" not in record.getMessage()


def test_health() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
