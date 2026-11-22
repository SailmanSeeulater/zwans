"""Tool calls a local model wrote as JSON in its reply become real calls."""

import json
from typing import Any

import pytest
from helpers import user
from test_providers_openai import Server, delta, finish, sse, stream_all

from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.text_calls import TextCall, find_call

TOOLS = {"Read", "Write", "Glob"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (  # qwen2.5-coder on Ollama
            'I\'ll start by reading it.\n\n{"name": "Read", "arguments": {\n  "path": "a.py"\n}}',
            TextCall("I'll start by reading it.", "Read", {"path": "a.py"}),
        ),
        (  # in a fence
            'Next:\n```json\n{"name": "Glob", "arguments": {"pattern": "*.py"}}\n```',
            TextCall("Next:", "Glob", {"pattern": "*.py"}),
        ),
        (  # in tags, with llama's key
            '<tool_call>\n{"name": "Read", "parameters": {"path": "b.py"}}\n</tool_call>',
            TextCall("", "Read", {"path": "b.py"}),
        ),
        (  # the API's own form, arguments as a string
            json.dumps(
                {"type": "function", "function": {"name": "Read", "arguments": '{"path": "c"}'}}
            ),
            TextCall("", "Read", {"path": "c"}),
        ),
    ],
)
def test_a_call_written_as_json_is_found(text: str, expected: TextCall) -> None:
    assert find_call(text, TOOLS) == expected


def test_only_the_first_call_counts() -> None:
    text = (
        '{"name": "Read", "arguments": {"path": "app.py"}}\n'
        '{"name": "Write", "arguments": {"path": "answer.txt", "content": "7"}}'
    )

    assert find_call(text, TOOLS) == TextCall("", "Read", {"path": "app.py"})


@pytest.mark.parametrize(
    "text",
    [
        "Done. The tests pass.",
        '{"name": "RunTests", "arguments": {}}',  # not a tool this request offered
        'The config is {"name": "Read"}.',  # no arguments: data, not a call
        '{"name": "Read", "arguments": {"path": "a"}, "result": "..."}',  # not a call's shape
        '{"name": "Read", "arguments": ["a.py"]}',
        '{"name": "Read", "arguments": {"path": "a.py"',  # cut off
    ],
)
def test_text_that_isnt_a_call_to_an_offered_tool_stays_text(text: str) -> None:
    assert find_call(text, TOOLS) is None


def chunks(text: str) -> list[dict[str, Any]]:
    return [delta(content=text[i : i + 7]) for i in range(0, len(text), 7)]


def test_the_provider_sends_a_call_written_in_the_text_as_a_real_one() -> None:
    call = json.dumps({"name": "Write", "arguments": {"path": "out.txt", "content": "hi"}})
    text = f"I will write the file.\n\n{call}\nThen I will check it."
    server = Server(sse(*chunks(text), finish("stop")))

    response = stream_all(server.provider(), [user("Write hi to out.txt")])[-1]

    text_block, tool_block = response.content
    assert text_block == TextBlock(text="I will write the file.")
    assert isinstance(tool_block, ToolUseBlock)
    assert (tool_block.name, tool_block.input) == ("Write", {"path": "out.txt", "content": "hi"})
    assert tool_block.id.startswith("call_")
    assert response.stop_reason == "tool_use"


def test_a_reply_with_real_calls_is_left_as_it_is() -> None:
    written = '{"name": "Write", "arguments": {"path": "x", "content": ""}}'
    server = Server(
        sse(
            delta(content=f"For example: {written}"),
            delta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c1",
                        "function": {"name": "Write", "arguments": '{"path": "y", "content": ""}'},
                    }
                ]
            ),
            finish("tool_calls"),
        )
    )

    response = stream_all(server.provider(), [user("hi")])[-1]

    assert [type(block) for block in response.content] == [TextBlock, ToolUseBlock]
    assert response.content[1].input == {"path": "y", "content": ""}
