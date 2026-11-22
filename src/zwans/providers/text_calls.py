"""Tool calls a model wrote in its reply's text instead of sending them as calls.

Some local models (qwen2.5-coder on Ollama is one) write a call as JSON in the text, such as
`{"name": "Read", "arguments": {"path": "a.py"}}`, when the server's chat template doesn't
turn it into a call. Taken as text, the reply ends the turn with nothing done. This finds
the first such call to a tool the request offered, so the provider can send it as a real
one. Only the first: whatever follows it was written without that call's result, so it is
often made up (a model may write a whole chain of calls and their outcomes).
"""

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

ARGUMENT_KEYS = ("arguments", "parameters", "input")  # qwen, llama, Claude's own name
ALLOWED_KEYS = {"name", "type", "id", *ARGUMENT_KEYS}
# What may open a call written as text, right before the object: a fence or a tag.
OPENING = re.compile(r"(?:```[a-z_]*|<tool_call>|<function_call>)\s*\Z", re.IGNORECASE)


@dataclass(frozen=True)
class TextCall:
    before: str  # the reply's text before the call, without the fence or tag that opened it
    name: str
    input: dict[str, Any]


def find_call(text: str, tools: Collection[str]) -> TextCall | None:
    """The first call in `text` to one of `tools`, written as JSON, or None."""
    if not tools or "{" not in text:
        return None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        call = _as_call(value, tools)
        if call is not None:
            before = OPENING.sub("", text[: match.start()]).rstrip()
            return TextCall(before=before, name=call[0], input=call[1])
    return None


def _as_call(value: object, tools: Collection[str]) -> tuple[str, dict[str, Any]] | None:
    if isinstance(value, dict) and isinstance(value.get("function"), dict):
        value = value["function"]  # {"type": "function", "function": {...}}
    if not isinstance(value, dict) or not set(value) <= ALLOWED_KEYS:
        return None
    name = value.get("name")
    keys = [key for key in ARGUMENT_KEYS if key in value]
    if not isinstance(name, str) or name not in tools or len(keys) != 1:
        return None
    arguments = value[keys[0]]
    if isinstance(arguments, str):  # the API's own form: the arguments as a JSON string
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if not isinstance(arguments, dict):
        return None
    return name, arguments
