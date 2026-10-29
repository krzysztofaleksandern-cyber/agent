"""Tool-calling agent loop with delegation, approvals and memory hooks."""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.agents.profiles import AgentProfile, AgentRegistry
from app.llm.base import LLMClient
from app.llm.types import ChatMessage, LLMResponse, ToolCall, Usage
from app.logging import preview
from app.sandbox.runner import SandboxRunner
from app.tools.base import Tool, ToolContext, ToolError
from app.tools.builtin import get_tools

log = logging.getLogger(__name__)

MAX_TOOL_OUTPUT = 12_000
FINAL_PROMPT = (
    "Step limit reached. Do not call tools. Summarize what was done, the current state "
    "and the next steps."
)


class Approver(Protocol):
    async def review(self, tool: str, args: dict[str, Any], client: str) -> str | None:
        """None = allowed; otherwise the reason the action was refused."""
        ...


class Memory(Protocol):
    async def context(self, agent: str, query: str) -> str: ...

    async def record(
        self, agent: str, client: str, messages: list[ChatMessage], answer: str
    ) -> int | None: ...


@dataclass
class AgentResult:
    content: str
    agent: str
    steps: int
    stopped: str  # "final" | "max_steps"
    usage: Usage = field(default_factory=Usage)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    interaction_id: int | None = None

    def as_response(self) -> LLMResponse:
        return LLMResponse(
            content=self.content, model=self.agent, finish_reason="stop", usage=self.usage
        )


def safe_name(client: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", client) or "default"


_TOOL_BLOCK = re.compile(r"```tool\s*(\{.*?\})\s*```", re.DOTALL)


def parse_text_tool_calls(content: str | None) -> list[ToolCall]:
    """Tool calls for models without native function calling (```tool {json}``` blocks)."""
    if not content:
        return []
    blobs = _TOOL_BLOCK.findall(content)
    if not blobs and content.strip().startswith("{"):
        blobs = [content.strip()]
    calls = []
    for blob in blobs:
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            args = data.get("arguments") or {}
            calls.append(
                ToolCall(id=f"text_{uuid.uuid4().hex[:8]}", name=data["name"],
                         arguments=json.dumps(args))
            )  # fmt: skip
    return calls


def _text_protocol(tools: list[Tool]) -> str:
    specs = "\n".join(
        f"- {t.name}: {t.description} Parameters (JSON schema): {json.dumps(t.parameters)}"
        for t in tools
    )
    return (
        "\n\n## Tools\nYou can call tools. To call one, reply with ONLY a block like:\n"
        '```tool\n{"name": "<tool>", "arguments": {...}}\n```\n'
        "You will receive the result in the next message. When finished, answer normally "
        f"without a tool block.\nAvailable tools:\n{specs}"
    )


class AgentRunner:
    def __init__(
        self,
        llm: LLMClient,
        agents: AgentRegistry,
        sandbox: SandboxRunner,
        workspaces_dir: Path,
        http_allowlist: list[str] | None = None,
        approver: Approver | None = None,
        memory: Memory | None = None,
        max_depth: int = 2,
        http: httpx.AsyncClient | None = None,
        operator_hub: Any = None,
        services: dict[str, Any] | None = None,
        audit: Any = None,
        control: Any = None,
    ) -> None:
        self.llm = llm
        self.agents = agents
        self.sandbox = sandbox
        self.workspaces_dir = workspaces_dir
        self.http_allowlist = http_allowlist or []
        self.approver = approver
        self.memory = memory
        self.max_depth = max_depth
        self.http = http
        self.operator_hub = operator_hub
        self.services = services or {}
        self.audit = audit
        self.control = control
        self.max_images = 2

    def workspace(self, client: str) -> Path:
        path = self.workspaces_dir / safe_name(client)
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def run(
        self, agent_name: str, messages: list[ChatMessage], client: str = "", depth: int = 0
    ) -> AgentResult:
        profile = self.agents.get(agent_name)
        if profile is None:
            raise KeyError(agent_name)
        tools = get_tools(profile.tools)
        by_name = {t.name: t for t in tools}
        ctx = ToolContext(
            workspace=self.workspace(client),
            sandbox=self.sandbox,
            client=client,
            http_allowlist=self.http_allowlist,
            http=self.http,
            delegate=self._delegate_fn(client, depth),
            delegates=profile.delegates if depth < self.max_depth else [],
            operator_hub=self.operator_hub,
            services=self.services,
        )
        convo = [{"role": "system", "content": await self._system_prompt(profile, tools, messages)}]
        convo += messages
        native = profile.native_tools
        schemas = [t.schema() for t in tools] if native and tools else None
        usage = Usage()
        tool_log: list[dict[str, Any]] = []

        for step in range(1, profile.max_steps + 1):
            resp = await self.llm.chat(
                convo, model=profile.model, tools=schemas, temperature=profile.temperature
            )
            usage = _add(usage, resp.usage)
            calls = resp.tool_calls if native else parse_text_tool_calls(resp.content)
            if not calls:
                return await self._finish(
                    profile, client, messages, resp.content or "", step, "final", usage, tool_log
                )
            if self.control is not None and self.control.paused:
                return await self._finish(
                    profile,
                    client,
                    messages,
                    "Paused by the owner — no actions were taken. Resume from the phone.",
                    step,
                    "paused",
                    usage,
                    tool_log,
                )
            convo.append(resp.to_message() if native else {"role": "assistant",
                                                            "content": resp.content})  # fmt: skip
            for call in calls:
                output, ok = await self._execute(call, by_name, ctx)
                tool_log.append({"step": step, "tool": call.name, "ok": ok,
                                 "args": preview(call.arguments, 120)})  # fmt: skip
                if self.audit is not None:
                    note = None if ok else output[:200]
                    await asyncio.to_thread(
                        self.audit.record, profile.name, client, call.name,
                        preview(call.arguments, 200), ok, note,
                    )  # fmt: skip
                if native:
                    convo.append({"role": "tool", "tool_call_id": call.id, "content": output})
                else:
                    convo.append({"role": "user", "content": f"Result of {call.name}:\n{output}"})
            if ctx.images:
                content: list[dict[str, Any]] = [
                    {"type": "text", "text": "Current screen:"},
                    *(
                        {"type": "image_url", "image_url": {"url": url}}
                        for url in ctx.images[-self.max_images :]
                    ),
                ]
                convo.append({"role": "user", "content": content})
                ctx.images.clear()

        convo.append({"role": "user", "content": FINAL_PROMPT})
        resp = await self.llm.chat(convo, model=profile.model, temperature=profile.temperature)
        usage = _add(usage, resp.usage)
        return await self._finish(
            profile, client, messages, resp.content or "", profile.max_steps, "max_steps", usage,
            tool_log,
        )  # fmt: skip

    async def _system_prompt(
        self, profile: AgentProfile, tools: list[Tool], messages: list[ChatMessage]
    ) -> str:
        prompt = profile.system_prompt.rstrip()
        if tools:
            prompt += "\n\nYour working directory is /workspace (persistent per client)."
        if tools and not profile.native_tools:
            prompt += _text_protocol(tools)
        if self.memory is not None:
            query = next(
                (m.get("content") for m in reversed(messages) if m.get("role") == "user"), ""
            )
            if isinstance(query, str) and query:
                extra = await self.memory.context(profile.name, query)
                if extra:
                    prompt += "\n\n" + extra
        return prompt

    async def _finish(
        self,
        profile: AgentProfile,
        client: str,
        messages: list[ChatMessage],
        content: str,
        steps: int,
        stopped: str,
        usage: Usage,
        tool_log: list[dict[str, Any]],
    ) -> AgentResult:
        result = AgentResult(content, profile.name, steps, stopped, usage, tool_log)
        if self.memory is not None:
            try:
                result.interaction_id = await self.memory.record(
                    profile.name, client, messages, content
                )
            except Exception:
                log.exception("memory.record failed")
        log.info("agent %s finished steps=%d stopped=%s", profile.name, steps, stopped)
        return result

    async def _execute(
        self, call: ToolCall, tools: dict[str, Tool], ctx: ToolContext
    ) -> tuple[str, bool]:
        tool = tools.get(call.name)
        if tool is None:
            return f"ERROR: unknown tool {call.name!r}. Available: {sorted(tools)}", False
        try:
            args = json.loads(call.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as exc:
            return f"ERROR: invalid JSON arguments: {exc}", False
        if self.approver is not None:
            denied = await self.approver.review(call.name, args, ctx.client)
            if denied:
                return (
                    f"DENIED: {denied}. Do not retry this action; find another way or stop.",
                    False,
                )
        try:
            output = await tool.handler(args, ctx)
        except ToolError as exc:
            return f"ERROR: {exc}", False
        except Exception as exc:
            log.exception("tool %s crashed", call.name)
            return f"ERROR: tool crashed: {type(exc).__name__}", False
        if len(output) > MAX_TOOL_OUTPUT:
            output = output[:MAX_TOOL_OUTPUT] + f"\n…[{len(output) - MAX_TOOL_OUTPUT} chars cut]"
        return output, True

    def _delegate_fn(self, client: str, depth: int):
        async def delegate(agent: str, task: str) -> str:
            result = await self.run(
                agent, [{"role": "user", "content": task}], client=client, depth=depth + 1
            )
            return result.content

        return delegate


def _add(a: Usage, b: Usage) -> Usage:
    return Usage(a.prompt_tokens + b.prompt_tokens, a.completion_tokens + b.completion_tokens)
