import json
from pathlib import Path

import pytest

from app.agents.profiles import AgentRegistry
from app.learning.dataset import build_examples, to_jsonl
from app.learning.evaluate import EvalCase, load_cases, run_eval
from app.learning.pipeline import LearningPipeline
from app.learning.versions import ACTIVE, REJECTED, RETIRED, VersionStore
from app.llm.mock import MockLLM
from app.llm.registry import ModelRegistry, load_config
from app.llm.types import LLMResponse, LLMUnavailable
from app.memory.store import MemoryStore

ROOT = Path(__file__).parent.parent
YAML = """
backends: {gpu: {base_url: "http://gpu/v1"}}
default: coder
models:
  coder: {backend: gpu, model: base-coder}
"""


def test_eval_case_checks() -> None:
    case = EvalCase(prompt="p", expect_any=["Wien", "Vienna"], forbid=["Berlin"])
    assert case.check("It is vienna.")
    assert not case.check("Berlin or Vienna")
    assert not case.check("Paris")
    assert EvalCase(prompt="p", expect_regex=r"def f\(").check("def f(x): pass")


def test_repo_eval_yaml_loads() -> None:
    cases = load_cases(ROOT / "config/eval.yaml")
    assert cases["coder"] and all(isinstance(c, EvalCase) for c in cases["general"])


async def test_run_eval_handles_errors() -> None:
    llm = MockLLM(["Vienna", LLMUnavailable("x")])
    cases = [EvalCase("a", expect_any=["vienna"]), EvalCase("b", expect_any=["x"])]
    score, results = await run_eval(llm.chat, cases)
    assert score == 0.5 and results == [True, False]


def test_dataset(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    a = store.add_interaction("c", "codex", "fix bug", "fixed it", None)
    store.add_interaction("c", "codex", "fix bug", "fixed it", None)  # duplicate
    b = store.add_interaction("c", "codex", "bad", "wrong", None)
    store.rate(a, 5, None)
    store.rate(a + 1, 5, None)
    store.rate(b, 2, None)
    examples = build_examples(store.rated(4), {"codex": "You code."})
    assert len(examples) == 1
    assert examples[0]["messages"] == [
        {"role": "system", "content": "You code."},
        {"role": "user", "content": "fix bug"},
        {"role": "assistant", "content": "fixed it"},
    ]
    line = to_jsonl(examples).strip()
    assert json.loads(line) == examples[0]


def test_version_store_rollback(tmp_path: Path) -> None:
    vs = VersionStore(tmp_path / "v.db")
    v1 = vs.add("coder", "m:v1", "base")
    vs.activate(v1)
    v2 = vs.add("coder", "m:v2", "base")
    vs.activate(v2)
    assert vs.get(v1).status == RETIRED and vs.active()["coder"].id == v2
    back = vs.rollback("coder")
    assert back.id == v1 and back.status == ACTIVE and vs.get(v2).status == REJECTED
    assert vs.rollback("coder") is None
    assert vs.active() == {}


@pytest.fixture
def pipeline(tmp_path: Path):
    calls = []

    class Backend(MockLLM):
        async def chat(self, messages, **kw):
            calls.append(kw.get("model"))
            if kw.get("model") == "bad-model":
                return LLMResponse(content="I don't know", model="bad")
            if kw.get("model") == "base-coder":
                return LLMResponse(content="nope", model="base")
            return LLMResponse(content="def is_prime(n): return n > 1", model="good")

    cfg = tmp_path / "models.yaml"
    cfg.write_text(YAML)
    registry = ModelRegistry(load_config(cfg, {}), env={}, client_factory=lambda b, k: Backend())
    agents_yaml = tmp_path / "agents.yaml"
    agents_yaml.write_text("agents:\n  codex: {model: coder, system_prompt: You code.}\n")
    cases = {"coder": [EvalCase("write is_prime", expect_regex=r"def is_prime")]}
    pipe = LearningPipeline(
        registry,
        VersionStore(tmp_path / "v.db"),
        MemoryStore(tmp_path / "m.db"),
        AgentRegistry(agents_yaml, ["coder"]),
        cases,
    )
    return pipe, registry, calls


async def test_candidate_promotion_and_rollback(pipeline) -> None:
    pipe, registry, _ = pipeline
    bad = await pipe.evaluate_candidate("coder", "bad-model")
    assert not bad["promoted"] and registry.current_model("coder") == "base-coder"
    good = await pipe.evaluate_candidate("coder", "devagent-coder:v1", note="first")
    assert good["promoted"] and good["score"] == 1.0 and good["baseline_score"] == 0.0
    assert registry.current_model("coder") == "devagent-coder:v1"
    assert (await pipe.rollback("coder"))["model"] == "base-coder"
    assert registry.current_model("coder") == "base-coder"
    with pytest.raises(KeyError):
        await pipe.evaluate_candidate("ghost", "x")


async def test_apply_active_on_startup(pipeline) -> None:
    pipe, registry, _ = pipeline
    await pipe.evaluate_candidate("coder", "devagent-coder:v1")
    registry.set_model("coder", "base-coder")  # simulate restart
    pipe.apply_active()
    assert registry.current_model("coder") == "devagent-coder:v1"
