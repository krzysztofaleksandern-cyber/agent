"""Shared types for LLM clients (OpenAI chat-completions shape)."""

from dataclasses import dataclass, field
from typing import Any

# Messages and tool schemas are passed through in OpenAI wire format.
ChatMessage = dict[str, Any]
ToolSchema = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, parsed by the agent loop


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)

    def to_message(self) -> ChatMessage:
        """Assistant message to append to the conversation."""
        msg: ChatMessage = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        return msg


class LLMError(Exception):
    """Base error for LLM calls."""


class LLMUnavailable(LLMError):
    """Backend unreachable, overloaded or returned 5xx/429 (retryable / fallback-worthy)."""


class LLMTimeout(LLMUnavailable):
    """Request timed out."""


class LLMBadResponse(LLMError):
    """Backend rejected the request (4xx) or returned an unparseable body."""
