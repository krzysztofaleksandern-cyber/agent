from pathlib import Path

import pytest

from app.agents.profiles import AgentRegistry
from app.llm.registry import load_config

ROOT = Path(__file__).parent.parent


def test_repo_agents_yaml_is_valid() -> None:
    aliases = load_config(ROOT / "config/models.yaml", {"OLLAMA_URL": "http://x"}).models
    reg = AgentRegistry(ROOT / "config/agents.yaml", aliases)
    assert {"orchestrator", "codex", "writer", "auditor"} <= set(reg.names())
    assert reg.get("orchestrator").delegates == ["codex", "writer", "auditor"]


@pytest.mark.parametrize(
    "body",
    [
        "a: {model: zz, system_prompt: x}",
        "a: {model: m, system_prompt: x, tools: [rm_rf]}",
        "a: {model: m, system_prompt: x, tools: [delegate], delegates: [b]}",
        "a: {model: m, system_prompt: x, delegates: [a]}",
        "a: {model: m, system_prompt: x, colour: red}",
        "a: {model: m, system_prompt: x, max_steps: 0}",
    ],
)
def test_invalid_profiles(tmp_path: Path, body: str) -> None:
    p = tmp_path / "agents.yaml"
    p.write_text("agents:\n  " + body)
    with pytest.raises((ValueError, TypeError)):
        AgentRegistry(p, ["m"])


def test_upsert_rejects_invalid_and_keeps_state(tmp_path: Path) -> None:
    p = tmp_path / "agents.yaml"
    p.write_text("agents:\n  a: {model: m, system_prompt: x}\n")
    reg = AgentRegistry(p, ["m"])
    with pytest.raises(ValueError):
        reg.upsert("a", {"model": "nope"})
    assert reg.get("a").model == "m"
    reg.upsert("a", {"max_steps": 3})
    assert AgentRegistry(p, ["m"]).get("a").max_steps == 3


def test_office_agents_present_and_valid() -> None:
    aliases = load_config(ROOT / "config/models.yaml", {"OLLAMA_URL": "x", "GEMINI_API_KEYS": "k"})
    reg = AgentRegistry(ROOT / "config/agents.yaml", aliases.models)
    assert {"jarvis", "secretary", "researcher"} <= set(reg.names())
    jarvis = reg.get("jarvis")
    assert "operator" in jarvis.delegates and "secretary" in jarvis.delegates
    assert "delegate" in jarvis.tools
    # secretary reaches the computer only through the operator, not with raw os_* tools
    sec = reg.get("secretary")
    assert "operator" in sec.delegates
    assert not any(t.startswith("os_") for t in sec.tools)
