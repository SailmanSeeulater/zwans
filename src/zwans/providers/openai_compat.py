"""Calls a model through an OpenAI-compatible Chat Completions API and streams the reply.

Nearly every way to run a model that isn't Claude speaks this API: local servers (Ollama,
LM Studio, llama.cpp, vLLM), hosted open models (OpenRouter, Together, Fireworks, Groq,
DeepInfra) and other labs' APIs. The conversation stays in Zwans's own shape, which mirrors
the Messages API; this module translates it on the way out and the reply on the way back,
so a session can switch between Claude and these models.

Small models often get a tool call's input wrong: JSON that doesn't parse, a missing field,
a number where a string goes. Such a call is repaired before the loop sees it: the model is
asked again for just that input, with the tool's schema as the reply's required format,
which servers that support it (Ollama, vLLM, llama.cpp, LM Studio) enforce token by token.
Where the server can't, the call goes on as before: input that isn't JSON is asked for
again whole, and input that doesn't fit the schema reaches the tool, whose error the model
then reads.
"""

import asyncio
import json
import re
import secrets
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from zwans.config import Effort
from zwans.events import TextDelta, ThinkingDelta
from zwans.messages import (
    ImageBlock,
    Message,
    RawBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from zwans.providers.base import ModelResponse, ProviderError, StreamItem
from zwans.providers.text_calls import find_call
from zwans.tools.base import Tool, input_schema

STOP_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}
# Effort levels past what these APIs take ask for their most.
REASONING_EFFORT: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}
ATTEMPTS = 4  # in all, waiting 1, 2, 4 seconds in between
JSON_ATTEMPTS = 3
CONNECT_SECONDS = 10.0
# A local model can take minutes to load and to read a long conversation before its first
# token, so reads get a generous timeout.
READ_SECONDS = 600.0
VALID_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")  # what the Messages API takes as a tool call ID


@dataclass
class Endpoint:
    """Where a provider is and how to talk to it."""

    name: str  # the prefix in model names, as in "ollama/qwen3-coder:30b"
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    max_tokens: int | None = None  # sent only when set: servers know their models' limits
    reasoning_effort: bool = False  # send the effort level as reasoning_effort
    hint: str = ""  # what to check when the server can't be reached, as "Is Ollama running?"


class OpenAICompatProvider:
    def __init__(
        self,
        endpoint: Endpoint,
        model: str,
        effort: Effort = "medium",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model  # the model's ID on that server, without the provider prefix
        self.effort = effort
        self.last_request: dict[str, Any] | None = None
        headers = {**endpoint.headers}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"
        self._client = httpx.AsyncClient(
            base_url=endpoint.base_url.rstrip("/") + "/",
            headers=headers,
            timeout=httpx.Timeout(READ_SECONDS, connect=CONNECT_SECONDS),
            transport=transport,
        )

    @property
    def label(self) -> str:
        """The model's full name in Zwans, as usage and prices know it."""
        return f"{self.endpoint.name}/{self.model}"

    def set_model(self, model: str) -> None:
        self.model = model

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[StreamItem]:
        request = self.request(system, messages, tools)
        self.last_request = without_image_data(request)
        bad_json = 0
        attempt = 0
        while True:
            attempt += 1
            reply = _Reply()
            try:
                async with self._client.stream("POST", "chat/completions", json=request) as http:
                    if http.status_code >= 400:
                        body = (await http.aread()).decode("utf-8", "replace")
                        if http.status_code in RETRY_STATUSES and attempt < ATTEMPTS:
                            await asyncio.sleep(2 ** (attempt - 1))
                            continue
                        raise ProviderError(self._describe_status(http.status_code, body))
                    async for data in _sse_data(http):
                        for item in reply.add(data):
                            yield item
            except httpx.ConnectError as exc:
                raise ProviderError(self._unreachable()) from exc
            except httpx.TimeoutException as exc:
                if attempt < ATTEMPTS and not reply.started:
                    await asyncio.sleep(2 ** (attempt - 1))
                    continue
                raise ProviderError(
                    f"{self.endpoint.name} took too long to answer ({type(exc).__name__})."
                ) from exc
            except httpx.TransportError as exc:
                # Nothing from the cut-off reply was added to the conversation, so it's safe
                # to ask again; the user may see its first words twice.
                if attempt < ATTEMPTS:
                    await asyncio.sleep(2 ** (attempt - 1))
                    continue
                raise ProviderError(
                    f"The connection to {self.endpoint.name} kept dropping mid-reply ({exc!r})."
                ) from exc
            response = reply.response(self.label, {tool.name: input_schema(tool) for tool in tools})
            broken = reply.broken + _misfits(response, tools, reply.broken)
            unfixed = [b for b in broken if not await self._repair(request, response, b, tools)]
            not_json = [b for b in unfixed if b.kind == "json"]
            if not_json:
                bad_json += 1
                if bad_json < JSON_ATTEMPTS:
                    attempt = 0
                    continue
                raise ProviderError(
                    f"{self.label} kept sending tool input that isn't a JSON object: "
                    f"{not_json[0].name}: {not_json[0].raw[:200]!r}"
                )
            yield response
            return

    async def _repair(
        self,
        request: dict[str, Any],
        response: ModelResponse,
        broken: "_Broken",
        tools: Sequence[Tool[Any]],
    ) -> bool:
        """Ask again for `broken`'s input alone, in the tool's schema, and put it in the call.
        False, changing nothing, when the server can't constrain its reply or the new input
        doesn't fit either."""
        tool = next((t for t in tools if t.name == broken.name), None)
        if tool is None:
            return False
        said = "".join(b.text for b in response.content if isinstance(b, TextBlock))
        messages = [
            *request["messages"],
            {"role": "assistant", "content": f"{said}\n\nCalling {broken.name} with: {broken.raw}"},
            {
                "role": "user",
                "content": f"That input for {broken.name} isn't valid: {broken.problem}. Write "
                f"the input for {broken.name} again, as JSON that fits its schema, and nothing "
                "else.",
            },
        ]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": broken.name, "schema": input_schema(tool)},
            },
        }
        if self.endpoint.max_tokens:
            body["max_tokens"] = self.endpoint.max_tokens
        try:
            http = await self._client.post("chat/completions", json=body)
            if http.status_code >= 400:
                return False  # no structured output here, or not for this model
            data = http.json()
            text = data["choices"][0]["message"]["content"]
            fixed = json.loads(text)
            tool.input_model.model_validate(fixed)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ValidationError):
            return False
        if not isinstance(fixed, dict):
            return False
        broken.block.input = fixed
        usage = data.get("usage") or {}
        response.input_tokens += int(usage.get("prompt_tokens") or 0)
        response.output_tokens += int(usage.get("completion_tokens") or 0)
        response.repairs += 1
        return True

    def request(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages(system, messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = [tool_param(t) for t in tools]
        if self.endpoint.max_tokens:
            body["max_tokens"] = self.endpoint.max_tokens
        if self.endpoint.reasoning_effort:
            body["reasoning_effort"] = REASONING_EFFORT[self.effort]
        return body

    def _describe_status(self, status: int, body: str) -> str:
        detail = body.strip()
        try:
            parsed = json.loads(body)
            error = parsed.get("error", parsed) if isinstance(parsed, dict) else parsed
            if isinstance(error, dict):
                detail = str(error.get("message") or error)
            elif isinstance(error, str):
                detail = error
        except ValueError:
            pass
        text = f"{self.endpoint.name} error {status}: {detail[:500]}"
        if status in (401, 403):
            text += " Check the provider's API key."
        elif status == 404 and "model" in detail.lower():
            text += (
                f" Is {self.model} the model's exact name there? "
                f"`zwans models {self.endpoint.name}` lists them."
            )
        return text

    def _unreachable(self) -> str:
        text = f"Couldn't reach {self.endpoint.name} at {self.endpoint.base_url}."
        return f"{text} {self.endpoint.hint}" if self.endpoint.hint else text

    async def aclose(self) -> None:
        await self._client.aclose()


async def list_models(endpoint: Endpoint, timeout: float = 3.0) -> list[str]:
    """The model IDs the server offers, from GET /models. Raises ProviderError."""
    headers = {**endpoint.headers}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key}"
    url = endpoint.base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.get(url)
    except httpx.ConnectError as exc:
        hint = f" {endpoint.hint}" if endpoint.hint else ""
        raise ProviderError(f"Couldn't reach {endpoint.base_url}.{hint}") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"Couldn't list models at {url}: {exc!r}") from exc
    if response.status_code >= 400:
        raise ProviderError(f"{url} answered {response.status_code}.")
    try:
        data = response.json().get("data", [])
        return sorted(str(m["id"]) for m in data if isinstance(m, dict) and "id" in m)
    except (ValueError, AttributeError) as exc:
        raise ProviderError(f"{url} didn't answer with a list of models.") from exc


@dataclass
class _Broken:
    """A tool call whose input is wrong, as the model sent it."""

    block: ToolUseBlock  # in the response, given the repaired input if there is one
    name: str
    raw: str  # the input as sent
    problem: str
    kind: str  # "json": not a JSON object at all; "schema": JSON that doesn't fit the tool


def _misfits(
    response: ModelResponse, tools: Sequence[Tool[Any]], not_json: Sequence[_Broken]
) -> list[_Broken]:
    """The calls in `response` whose input is JSON but doesn't fit their tool's input (those
    in `not_json` aside: their input isn't JSON at all)."""
    by_name = {tool.name: tool for tool in tools}
    skip = {id(b.block) for b in not_json}
    found = []
    for block in response.content:
        if not isinstance(block, ToolUseBlock) or id(block) in skip:
            continue
        tool = by_name.get(block.name)
        if tool is None:
            continue
        try:
            tool.input_model.model_validate(block.input)
        except ValidationError as exc:
            problem = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}"
                for e in exc.errors()[:5]
            )
            raw = json.dumps(block.input, ensure_ascii=False)
            found.append(_Broken(block, block.name, raw, problem, "schema"))
    return found


@dataclass
class _Call:
    id: str = ""
    name: str = ""
    arguments: str = ""


class _Reply:
    """A streamed reply, put together chunk by chunk."""

    def __init__(self) -> None:
        self.text = ""
        self.calls: dict[int, _Call] = {}
        self.finish = ""
        self.model = ""
        self.usage: dict[str, Any] = {}
        self.started = False  # something has been passed on to the user
        self.broken: list[_Broken] = []  # calls whose input isn't a JSON object, by response()

    def add(self, chunk: dict[str, Any]) -> list[StreamItem]:
        items: list[StreamItem] = []
        if isinstance(chunk.get("error"), dict | str):
            error = chunk["error"]
            message = error.get("message", error) if isinstance(error, dict) else error
            raise ProviderError(f"The model's server reported an error mid-reply: {message}")
        self.model = chunk.get("model") or self.model
        if isinstance(chunk.get("usage"), dict):
            self.usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            # Reasoning models send their thinking apart from the text, under one of these.
            thinking = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(thinking, str) and thinking:
                items.append(ThinkingDelta(text=thinking))
            text = delta.get("content")
            if isinstance(text, str) and text:
                self.text += text
                items.append(TextDelta(text=text))
            for part in delta.get("tool_calls") or []:
                index = part.get("index", len(self.calls))
                call = self.calls.setdefault(index, _Call())
                call.id = part.get("id") or call.id
                function = part.get("function") or {}
                if not call.name and function.get("name"):
                    call.name = function["name"]
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    call.arguments += arguments
                elif isinstance(arguments, dict):  # some servers send the object itself
                    call.arguments = json.dumps(arguments)
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]
        self.started = self.started or bool(items)
        return items

    def response(
        self, label: str, tools: Mapping[str, Mapping[str, Any]] | None = None
    ) -> ModelResponse:
        content: list[TextBlock | ToolUseBlock | RawBlock] = []
        written = None if self.calls else find_call(self.text, tools or {})
        if written is not None:
            # A call written in the text: what came before it stays text, the call becomes
            # a real one, and what followed (written without its result) is dropped.
            if written.before.strip():
                content.append(TextBlock(text=written.before))
            content.append(ToolUseBlock(id=_tool_id(""), name=written.name, input=written.input))
        elif self.text.strip():
            content.append(TextBlock(text=self.text))
        for _, call in sorted(self.calls.items()):
            if not call.name:
                continue
            try:
                arguments = json.loads(call.arguments) if call.arguments.strip() else {}
            except ValueError:
                arguments = None
            block = ToolUseBlock(
                id=_tool_id(call.id),
                name=call.name,
                input=arguments if isinstance(arguments, dict) else {},
            )
            if not isinstance(arguments, dict):
                problem = "it isn't a JSON object"
                self.broken.append(_Broken(block, call.name, call.arguments, problem, "json"))
            content.append(block)
        has_calls = any(isinstance(block, ToolUseBlock) for block in content)
        stop = "tool_use" if has_calls else STOP_REASONS.get(self.finish, "end_turn")
        prompt = int(self.usage.get("prompt_tokens") or 0)
        details = self.usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or self.usage.get("prompt_cache_hit_tokens") or 0)
        return ModelResponse(
            content=content,
            stop_reason=stop,
            model=label,
            input_tokens=max(prompt - cached, 0),
            output_tokens=int(self.usage.get("completion_tokens") or 0),
            cache_read_tokens=cached,
        )


async def _sse_data(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """The JSON objects in a server-sent event stream, until [DONE]."""
    async for line in response.aiter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            parsed = json.loads(data)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _tool_id(given: str) -> str:
    """A tool call ID both APIs take. Some local servers send none, or ones with characters
    the Messages API refuses, which would break the session after switching to Claude."""
    if given and VALID_ID.match(given):
        return given
    if given:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", given)[:64]
        if cleaned.strip("_"):
            return cleaned
    return f"call_{secrets.token_hex(8)}"


def chat_messages(system: str, messages: Sequence[Message]) -> list[dict[str, Any]]:
    """The conversation as Chat Completions messages.

    Tool results become "tool" messages straight after the call that asked for them, as the
    API requires; images in them follow in a user message, since tool messages hold text.
    Blocks only Claude reads, such as its thinking and web searches, are left out.
    """
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for message in messages:
        if message.role == "assistant":
            text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
            calls = [
                {
                    "id": b.id,
                    "type": "function",
                    "function": {"name": b.name, "arguments": json.dumps(b.input)},
                }
                for b in message.content
                if isinstance(b, ToolUseBlock)
            ]
            if not text and not calls:
                continue
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        parts: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                content = block.text()
                if block.is_error:
                    content = f"Error: {content}"
                out.append({"role": "tool", "tool_call_id": block.tool_use_id, "content": content})
                if isinstance(block.content, list):
                    parts += [_image_part(b) for b in block.content if isinstance(b, ImageBlock)]
            elif isinstance(block, TextBlock):
                parts.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageBlock):
                parts.append(_image_part(block))
        if not parts:
            continue
        if all(part["type"] == "text" for part in parts):
            # Plain text where there are no images: some servers take nothing else.
            out.append({"role": "user", "content": "\n\n".join(p["text"] for p in parts)})
        else:
            out.append({"role": "user", "content": parts})
    return out


def _image_part(block: ImageBlock) -> dict[str, Any]:
    url = f"data:{block.source.media_type};base64,{block.source.data}"
    return {"type": "image_url", "image_url": {"url": url}}


def tool_param(tool: Tool[Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": input_schema(tool),
        },
    }


def without_image_data(value: Any) -> Any:
    """A copy of a request with each image's data replaced by a note of its length."""
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.startswith("data:") and len(url) > 200:
            return {**value, "url": f"<{len(url):,} characters of image data>"}
        return {k: without_image_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [without_image_data(v) for v in value]
    return value
