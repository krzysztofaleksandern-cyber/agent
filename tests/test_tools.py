import shutil
from pathlib import Path

import httpx
import pytest

from app.sandbox.runner import BoundedBuffer, DockerSandbox, ExecResult, LocalRunner
from app.tools.base import ToolContext, ToolError, jail
from app.tools.builtin import TOOLS, get_tools, host_allowed


class FakeSandbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def run(self, command, workspace, timeout_s=None, network=False) -> ExecResult:
        self.calls.append((command, network))
        return ExecResult(0, "fake output")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    d = tmp_path / "ws"
    d.mkdir()
    return d


@pytest.fixture
def ctx(ws: Path) -> ToolContext:
    return ToolContext(workspace=ws, sandbox=FakeSandbox(), http_allowlist=["example.com"])


def test_jail(ws: Path, tmp_path: Path) -> None:
    assert jail(ws, "a/b.txt") == ws.resolve() / "a/b.txt"
    assert jail(ws, "/workspace/x.py") == ws.resolve() / "x.py"
    assert jail(ws, "/workspace") == ws.resolve()
    for bad in ["../x", "/etc/passwd", "a/../../x"]:
        with pytest.raises(ToolError):
            jail(ws, bad)
    (tmp_path / "secret").write_text("s")
    (ws / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(ToolError):
        jail(ws, "link")


async def test_file_tools(ctx: ToolContext) -> None:
    out = await TOOLS["write_file"].handler({"path": "src/a.py", "content": "x=1\ny=2\n"}, ctx)
    assert "src/a.py" in out
    assert (await TOOLS["read_file"].handler({"path": "src/a.py"}, ctx)) == "1| x=1\n2| y=2"
    assert await TOOLS["read_file"].handler({"path": "src/a.py", "start_line": 2}, ctx) == "2| y=2"
    listing = await TOOLS["list_dir"].handler({}, ctx)
    assert listing.splitlines() == ["src/", "src/a.py"]
    with pytest.raises(ToolError):
        await TOOLS["read_file"].handler({"path": "nope"}, ctx)
    with pytest.raises(ToolError):
        await TOOLS["write_file"].handler({"path": "../evil", "content": "x"}, ctx)


async def test_shell_and_git_use_sandbox(ctx: ToolContext) -> None:
    out = await TOOLS["shell"].handler({"command": "pytest -q"}, ctx)
    assert out.startswith("exit_code=0")
    await TOOLS["git"].handler({"args": ["status"]}, ctx)
    await TOOLS["git"].handler({"args": ["push", "origin", "main; rm -rf /"]}, ctx)
    await TOOLS["git"].handler({"args": "git log --oneline"}, ctx)
    calls = ctx.sandbox.calls
    assert calls[0] == ("pytest -q", False)
    assert calls[1] == ("git status", False)
    assert calls[2] == ("git push origin 'main; rm -rf /'", True)  # quoted, network on
    assert calls[3] == ("git log --oneline", False)
    with pytest.raises(ToolError):
        await TOOLS["git"].handler({}, ctx)


def test_host_allowlist() -> None:
    assert host_allowed("example.com", ["example.com"])
    assert host_allowed("www.Example.com", ["example.com"])
    assert not host_allowed("evilexample.com", ["example.com"])
    assert not host_allowed("example.com.evil.io", ["example.com"])


async def test_http_get(ctx: ToolContext) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.com/new"})
        if req.url.path == "/out":
            return httpx.Response(302, headers={"location": "https://evil.io/"})
        return httpx.Response(200, text="<title>Hi</title>", headers={"x-test": "1"})

    ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await TOOLS["http_get"].handler({"url": "https://example.com/old"}, ctx)
    assert out.startswith("HTTP 200 https://example.com/new") and "<title>Hi</title>" in out
    with pytest.raises(ToolError, match="allowlist"):
        await TOOLS["http_get"].handler({"url": "https://example.com/out"}, ctx)
    with pytest.raises(ToolError, match="allowlist"):
        await TOOLS["http_get"].handler({"url": "http://169.254.169.254/"}, ctx)
    with pytest.raises(ToolError):
        await TOOLS["http_get"].handler({"url": "file:///etc/passwd"}, ctx)


async def test_delegate_tool(ctx: ToolContext) -> None:
    async def fake(agent: str, task: str) -> str:
        return f"{agent} did {task}"

    ctx.delegate, ctx.delegates = fake, ["codex"]
    assert await TOOLS["delegate"].handler({"agent": "codex", "task": "x"}, ctx) == "codex did x"
    with pytest.raises(ToolError):
        await TOOLS["delegate"].handler({"agent": "writer", "task": "x"}, ctx)


def test_schemas() -> None:
    schemas = [t.schema() for t in get_tools(["shell", "git"])]
    assert schemas[0]["function"]["name"] == "shell"
    assert schemas[1]["function"]["parameters"]["required"] == ["args"]


def test_bounded_buffer() -> None:
    buf = BoundedBuffer(10)
    for _ in range(10):
        buf.feed(b"abcdefgh")
    text, truncated = buf.text()
    assert truncated and text.startswith("abcde") and text.endswith("defgh")
    small = BoundedBuffer(100)
    small.feed(b"hello")
    assert small.text() == ("hello", False)


async def test_local_runner(ws: Path) -> None:
    runner = LocalRunner(timeout_s=5, max_output=200)
    res = await runner.run("echo hi && exit 3", ws)
    assert res.exit_code == 3 and res.output.strip() == "hi"
    res = await runner.run("sleep 5", ws, timeout_s=0.2)
    assert res.timed_out
    res = await runner.run("yes | head -c 100000", ws)
    assert res.truncated and len(res.output) < 400


def test_docker_args(ws: Path) -> None:
    args = DockerSandbox(cpus=0.5, memory="512m").build_args("ls", ws, False, "n1")
    joined = " ".join(args)
    for flag in ["--network none", "--cpus 0.5", "--memory 512m", "--pids-limit 256",
                 "--read-only", "--cap-drop ALL", "no-new-privileges", "--rm"]:  # fmt: skip
        assert flag in joined
    assert args[-3:] == ["sh", "-lc", "ls"]
    assert "--network bridge" in " ".join(DockerSandbox().build_args("x", ws, True, "n"))


@pytest.mark.docker
async def test_docker_sandbox_real(ws: Path) -> None:
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    res = await DockerSandbox(image="python:3.12-slim").run("echo ok; id -u", ws)
    assert res.exit_code == 0 and "ok" in res.output and "1000" in res.output
