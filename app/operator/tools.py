"""Operator agent tools. Each one is executed on the owner's computer by the host worker
(via OperatorHub.dispatch); nothing here runs on the VPS itself."""

from typing import Any

from app.operator.hub import OperatorHub, WorkerOffline
from app.tools.base import Tool, ToolContext, ToolError

# Actions that change the machine -> routed through the approval gate (see app/approvals).
RISKY_ACTIONS = {"os_shell", "os_run", "os_write_file", "os_delete"}


async def _call(ctx: ToolContext, action: str, params: dict[str, Any]) -> str:
    hub: OperatorHub | None = ctx.operator_hub
    if hub is None:
        raise ToolError("operator hub is not configured")
    try:
        result = await hub.dispatch(action, params)
    except WorkerOffline as exc:
        raise ToolError(f"computer not reachable: {exc}") from exc
    if not result.get("ok", False):
        raise ToolError(result.get("error", "command failed on the computer"))
    return str(result.get("output", ""))


def _tool(name: str, desc: str, props: dict[str, Any], required: list[str]) -> Tool:
    async def handler(args: dict[str, Any], ctx: ToolContext, _action: str = name) -> str:
        return await _call(ctx, _action, args)

    return Tool(name, desc, {"type": "object", "properties": props, "required": required}, handler)


OPERATOR_TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        _tool(
            "screenshot",
            "Take a screenshot of the computer screen and return a description "
            "plus the saved image reference.",
            {},
            [],
        ),
        _tool(
            "mouse_move",
            "Move the mouse to absolute screen coordinates.",
            {"x": {"type": "integer"}, "y": {"type": "integer"}},
            ["x", "y"],
        ),
        _tool(
            "mouse_click",
            "Click the mouse at the given coordinates (or current position).",
            {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"]},
                "double": {"type": "boolean"},
            },
            [],
        ),
        _tool(
            "mouse_scroll",
            "Scroll vertically by the given amount (positive = up).",
            {"amount": {"type": "integer"}},
            ["amount"],
        ),
        _tool("type_text", "Type text with the keyboard.", {"text": {"type": "string"}}, ["text"]),
        _tool(
            "key_press",
            "Press a key or hotkey combo, e.g. 'enter' or 'ctrl+c'.",
            {"keys": {"type": "string"}},
            ["keys"],
        ),
        _tool(
            "os_run",
            "Launch a program / open a file or URL on the computer.",
            {"target": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}},
            ["target"],
        ),
        _tool(
            "os_shell",
            "Run a PowerShell command on the computer and return its output.",
            {"command": {"type": "string"}, "timeout": {"type": "number"}},
            ["command"],
        ),
        _tool(
            "os_read_file",
            "Read a text file from the computer by absolute path.",
            {"path": {"type": "string"}},
            ["path"],
        ),
        _tool(
            "os_write_file",
            "Write a text file on the computer by absolute path.",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        ),
        _tool(
            "os_list_dir",
            "List a directory on the computer.",
            {"path": {"type": "string"}},
            ["path"],
        ),
    ]
}
