"""Built-in agent tools."""

import shlex
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.tools.base import Tool, ToolContext, ToolError, jail

MAX_READ_BYTES = 200_000
MAX_HTTP_BYTES = 200_000
MAX_LIST_ENTRIES = 500
NETWORK_GIT_COMMANDS = {"push", "pull", "fetch", "clone", "ls-remote"}


def _str(args: dict[str, Any], key: str, default: str | None = None) -> str:
    value = args.get(key, default)
    if not isinstance(value, str) or (default is None and not value):
        raise ToolError(f"argument '{key}' (string) is required")
    return value


async def shell(args: dict[str, Any], ctx: ToolContext) -> str:
    command = _str(args, "command")
    timeout = args.get("timeout")
    result = await ctx.sandbox.run(
        command, ctx.workspace, timeout_s=float(timeout) if timeout else None
    )
    return result.render()


async def read_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = jail(ctx.workspace, _str(args, "path"))
    if not path.is_file():
        raise ToolError(f"not a file: {args['path']}")
    data = path.read_bytes()[:MAX_READ_BYTES]
    if b"\0" in data[:8000]:
        raise ToolError("binary file")
    lines = data.decode(errors="replace").splitlines()
    start = max(int(args.get("start_line") or 1), 1)
    end = int(args.get("end_line") or len(lines))
    width = len(str(end))
    body = "\n".join(
        f"{i:>{width}}| {line}" for i, line in enumerate(lines[start - 1 : end], start)
    )
    note = "\n[file truncated]" if path.stat().st_size > MAX_READ_BYTES else ""
    return (body or "[empty file]") + note


async def write_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = jail(ctx.workspace, _str(args, "path"))
    content = _str(args, "content", default="")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"wrote {len(content.encode())} bytes to {path.relative_to(ctx.workspace.resolve())}"


async def list_dir(args: dict[str, Any], ctx: ToolContext) -> str:
    root = jail(ctx.workspace, _str(args, "path", default="."))
    if not root.is_dir():
        raise ToolError(f"not a directory: {args.get('path')}")
    depth = min(int(args.get("depth") or 2), 5)
    base = ctx.workspace.resolve()
    entries: list[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if ".git" in rel.parts or "node_modules" in rel.parts or len(rel.parts) > depth:
            continue
        entries.append(str(p.relative_to(base)) + ("/" if p.is_dir() else ""))
        if len(entries) >= MAX_LIST_ENTRIES:
            entries.append("…[listing truncated]")
            break
    return "\n".join(entries) or "[empty directory]"


async def git(args: dict[str, Any], ctx: ToolContext) -> str:
    raw = args.get("args")
    argv = shlex.split(raw) if isinstance(raw, str) else raw
    if not argv or not all(isinstance(a, str) for a in argv):
        raise ToolError("argument 'args' (list of strings) is required, e.g. ['status']")
    if argv[0] == "git":
        argv = argv[1:]
    sub = next((a for a in argv if not a.startswith("-")), "")
    result = await ctx.sandbox.run(
        shlex.join(["git", *argv]), ctx.workspace, network=sub in NETWORK_GIT_COMMANDS
    )
    return result.render()


def host_allowed(host: str, allowlist: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in allowlist)


async def http_get(args: dict[str, Any], ctx: ToolContext) -> str:
    url = _str(args, "url")
    client = ctx.http or httpx.AsyncClient(timeout=20.0)
    try:
        for _ in range(4):  # follow up to 3 redirects, re-checking the allowlist each hop
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ToolError(f"invalid URL: {url}")
            if not host_allowed(parsed.hostname, ctx.http_allowlist):
                raise ToolError(f"domain not in allowlist: {parsed.hostname}")
            async with client.stream("GET", url, follow_redirects=False) as resp:
                if resp.is_redirect and "location" in resp.headers:
                    url = urljoin(url, resp.headers["location"])
                    continue
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) >= MAX_HTTP_BYTES:
                        break
                headers = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
                text = bytes(body[:MAX_HTTP_BYTES]).decode(errors="replace")
                return f"HTTP {resp.status_code} {url}\n{headers}\n\n{text}"
        raise ToolError("too many redirects")
    except httpx.HTTPError as exc:
        raise ToolError(f"request failed: {type(exc).__name__}") from exc
    finally:
        if ctx.http is None:
            await client.aclose()


async def delegate(args: dict[str, Any], ctx: ToolContext) -> str:
    agent, task = _str(args, "agent"), _str(args, "task")
    if ctx.delegate is None or agent not in ctx.delegates:
        raise ToolError(f"cannot delegate to {agent!r}; allowed: {ctx.delegates}")
    return await ctx.delegate(agent, task)


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "shell",
            "Run a shell command in the /workspace sandbox (no network). Returns exit code "
            "and combined output.",
            _obj(
                {
                    "command": {"type": "string"},
                    "timeout": {"type": "number", "description": "seconds"},
                },
                ["command"],
            ),
            shell,
        ),
        Tool(
            "read_file",
            "Read a text file from /workspace with line numbers.",
            _obj(
                {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                ["path"],
            ),
            read_file,
        ),
        Tool(
            "write_file",
            "Create or overwrite a file in /workspace with the given content.",
            _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            write_file,
        ),
        Tool(
            "list_dir",
            "List files under a directory in /workspace.",
            _obj({"path": {"type": "string"}, "depth": {"type": "integer"}}, []),
            list_dir,
        ),
        Tool(
            "git",
            "Run git with the given arguments in /workspace, e.g. {'args': ['status']}.",
            _obj({"args": {"type": "array", "items": {"type": "string"}}}, ["args"]),
            git,
        ),
        Tool(
            "http_get",
            "HTTP GET a URL (only allowlisted domains). Returns status, headers and body.",
            _obj({"url": {"type": "string"}}, ["url"]),
            http_get,
        ),
        Tool(
            "delegate",
            "Hand a self-contained task to another agent and get its final answer.",
            _obj({"agent": {"type": "string"}, "task": {"type": "string"}}, ["agent", "task"]),
            delegate,
        ),
    ]
}


def _all_tools() -> dict[str, Tool]:
    from app.connectors.mail_tools import MAIL_TOOLS
    from app.operator.tools import OPERATOR_TOOLS

    return {**TOOLS, **OPERATOR_TOOLS, **MAIL_TOOLS}


def get_tools(names: list[str]) -> list[Tool]:
    registry = _all_tools()
    return [registry[n] for n in names]
