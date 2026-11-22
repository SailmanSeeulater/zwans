"""A local model's broken tool input is asked for again in the tool's schema, which the
server enforces, before the loop ever sees it."""

from typing import Any

import httpx
from helpers import user
from test_providers_openai import Server, delta, finish, sse, stream_all, usage

from zwans.messages import ToolUseBlock
from zwans.providers.base import ModelResponse


def calls_write(arguments: str) -> bytes:
    call = {"index": 0, "id": "c1", "function": {"name": "Write", "arguments": arguments}}
    return sse(delta(tool_calls=[call]), finish("tool_calls"), usage(prompt=1000, completion=30))


def answer(content: str, prompt: int = 1100, completion: int = 20) -> httpx.Response:
    message = {"role": "assistant", "content": content}
    body: dict[str, Any] = {
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }
    return httpx.Response(200, json=body)


NO_SCHEMAS = httpx.Response(400, json={"error": {"message": "structured output is unavailable"}})


def test_input_that_isnt_json_is_repaired_in_the_tools_schema() -> None:
    server = Server(
        calls_write('{"path": "a.txt", "content": "hi'),  # cut off
        answer('{"path": "a.txt", "content": "hi"}'),
    )

    response = stream_all(server.provider(), [user("Make a.txt")])[-1]

    assert isinstance(response, ModelResponse)
    assert response.content == [
        ToolUseBlock(id="c1", name="Write", input={"path": "a.txt", "content": "hi"})
    ]
    assert response.repairs == 1
    assert (response.input_tokens, response.output_tokens) == (2100, 50)  # both requests
    repair = server.bodies[1]
    assert repair["stream"] is False and "tools" not in repair
    schema = repair["response_format"]["json_schema"]
    assert schema["name"] == "Write" and "path" in schema["schema"]["properties"]
    assert "isn't a JSON object" in repair["messages"][-1]["content"]
    assert '"content": "hi' in repair["messages"][-2]["content"]  # what it sent, to fix


def test_input_that_doesnt_fit_the_tool_is_repaired_too() -> None:
    server = Server(
        calls_write('{"file": "a.txt", "content": "hi"}'),  # the wrong name for path
        answer('{"path": "a.txt", "content": "hi"}'),
    )

    response = stream_all(server.provider(), [user("Make a.txt")])[-1]

    assert response.content[0].input == {"path": "a.txt", "content": "hi"}
    assert "path: Field required" in server.bodies[1]["messages"][-1]["content"]


def test_without_structured_output_a_misfit_reaches_the_tool_as_it_was() -> None:
    server = Server(calls_write('{"file": "a.txt", "content": "hi"}'), NO_SCHEMAS)

    response = stream_all(server.provider(), [user("Make a.txt")])[-1]

    # The tool's own error tells the model what's wrong, as before.
    assert response.content[0].input == {"file": "a.txt", "content": "hi"}
    assert response.repairs == 0


def test_a_repair_that_still_doesnt_fit_changes_nothing() -> None:
    server = Server(calls_write('{"file": "a.txt"}'), answer('{"path": 3}'))

    response = stream_all(server.provider(), [user("Make a.txt")])[-1]

    assert response.content[0].input == {"file": "a.txt"} and response.repairs == 0


def test_good_input_costs_no_extra_request() -> None:
    server = Server(calls_write('{"path": "a.txt", "content": "hi"}'))

    stream_all(server.provider(), [user("Make a.txt")])

    assert len(server.bodies) == 1
