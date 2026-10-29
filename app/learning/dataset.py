"""Build fine-tuning datasets (chat-format JSONL) from owner-rated interactions."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from app.memory.store import Interaction


def build_examples(
    interactions: Iterable[Interaction],
    system_prompts: Mapping[str, str] | None = None,
    min_answer_chars: int = 2,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    examples = []
    for i in interactions:
        prompt, answer = i.prompt.strip(), i.answer.strip()
        if len(answer) < min_answer_chars or not prompt:
            continue
        digest = hashlib.sha256(f"{i.agent}\0{prompt}\0{answer}".encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        messages = []
        system = (system_prompts or {}).get(i.agent)
        if system:
            messages.append({"role": "system", "content": system})
        messages += [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}]
        examples.append({"messages": messages})
    return examples


def to_jsonl(examples: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples)
