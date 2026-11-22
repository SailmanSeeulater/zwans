"""Tool calls a model wrote in its reply's text instead of sending them as calls.

Some local models (qwen2.5-coder on Ollama is one) write a call as JSON in the text, such as
`{"name": "Read", "arguments": {"path": "a.py"}}`, when the server's chat template doesn't
turn it into a call. Taken as text, the reply ends the turn with nothing done. This finds
the first such call to a tool the request offered, so the provider can send it as a real
one. Only the first: whatever follows it was written without that call's result, so it is
often made up (a model may write a whole chain of calls and their outcomes).

Qwen3-Coder has a form of its own, which it falls back to in the text when the server's
parser misses a call (after a sentence of preamble, say):

    <function=Read>
    <parameter=path>
    a.py
    </parameter>
    </function>

Its values are bare text, so each is read as the type the tool's schema gives that parameter.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

ARGUMENT_KEYS = ("arguments", "parameters", "input")  # qwen, llama, Claude's own name
ALLOWED_KEYS = {"name", "type", "id", *ARGUMENT_KEYS}
# What may open a call written as text, right before the object: a fence or a tag.
OPENING = re.compile(r"(?:```[a-z_]*|<tool_call>|<function_call>)\s*\Z", re.IGNORECASE)
XML_CALL = re.compile(r"<function=([\w.-]+)>(.*?)</function>", re.DOTALL)
XML_PARAMETER = re.compile(r"<parameter=([\w.-]+)>\n?(.*?)\n?</parameter>", re.DOTALL)


@dataclass(frozen=True)
class TextCall:
    before: str  # the reply's text before the call, without the fence or tag that opened it
    name: str
    input: dict[str, Any]


def find_call(text: str, tools: Mapping[str, Mapping[str, Any]]) -> TextCall | None:
    """The first call in `text` to one of `tools` (each name with its input schema), written
    as JSON or in Qwen3-Coder's form, or None."""
    if not tools:
        return None
    found = [call for call in (_json_call(text, tools), _xml_call(text, tools)) if call]
    if not found:
        return None
    start, name, arguments = min(found, key=lambda call: call[0])
    before = OPENING.sub("", text[:start]).rstrip()
    return TextCall(before=before, name=name, input=arguments)


def _json_call(text: str, tools: Mapping[str, Any]) -> tuple[int, str, dict[str, Any]] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        call = _as_call(value, tools)
        if call is not None:
            return match.start(), *call
    return None


def _xml_call(
    text: str, tools: Mapping[str, Mapping[str, Any]]
) -> tuple[int, str, dict[str, Any]] | None:
    for match in XML_CALL.finditer(text):
        name = match.group(1)
        if name not in tools:
            continue
        properties = tools[name].get("properties") or {}
        arguments = {
            key: _typed(value, properties.get(key) or {})
            for key, value in XML_PARAMETER.findall(match.group(2))
        }
        return match.start(), name, arguments
    return None


def _typed(value: str, schema: Mapping[str, Any]) -> Any:
    """`value` as the type `schema` gives, when it reads as one; otherwise as it is. A value
    that still doesn't fit is caught with the rest of the call's input, and repaired."""
    types = _types(schema)
    if not types or "string" in types:
        return value
    try:
        return json.loads(value)
    except ValueError:
        stripped = value.strip()
        return {"True": True, "False": False}.get(stripped, stripped)


def _types(schema: Mapping[str, Any]) -> set[str]:
    kind = schema.get("type")
    types = {kind} if isinstance(kind, str) else set(kind) if isinstance(kind, list) else set()
    for option in schema.get("anyOf") or schema.get("oneOf") or []:
        if isinstance(option, Mapping):
            types |= _types(option)
    return types - {"null"}


def _as_call(value: object, tools: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
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
