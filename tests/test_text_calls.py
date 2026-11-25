"""Tool calls a local model wrote in its reply, as JSON or in Qwen3-Coder's form, become real
calls."""

import json
from typing import Any

import pytest
from helpers import user
from test_providers_openai import Server, delta, finish, sse, stream_all

from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.text_calls import TextCall, find_call

TOOLS: dict[str, dict[str, Any]] = {
    "Read": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
    },
    "Write": {"properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
    "Glob": {"properties": {"pattern": {"type": "string"}}},
    "Edits": {
        "properties": {
            "edits": {"type": "array"},
            "all": {"type": "boolean"},
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        }
    },
}


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


def test_an_mcp_tool_called_by_its_own_name_is_found_when_only_one_server_has_it() -> None:
    tools = {
        **TOOLS,
        "mcp__zands__search_news": {"properties": {"query": {"type": "string"}}},
        "mcp__a__lookup": {"properties": {}},
        "mcp__b__lookup": {"properties": {}},
    }
    # qwen2.5-coder on Ollama, with the server prefix left off
    text = '{"name": "search_news", "arguments": {"query": "capital of Australia"}}'
    assert find_call(text, tools) == TextCall(
        "", "mcp__zands__search_news", {"query": "capital of Australia"}
    )
    xml = "<function=search_news>\n<parameter=query>\nNvidia\n</parameter>\n</function>"
    assert find_call(xml, tools) == TextCall("", "mcp__zands__search_news", {"query": "Nvidia"})
    assert find_call('{"name": "lookup", "arguments": {}}', tools) is None  # two servers
    assert find_call('{"name": "news", "arguments": {}}', tools) is None  # not a whole name
    assert find_call('{"name": "Search", "arguments": {}}', tools) is None  # not a built-in


def test_a_tool_named_in_another_case_is_found() -> None:
    # qwen2.5-coder on Ollama ended a turn with this as its answer, WebSearch being offered.
    tools = {**TOOLS, "WebSearch": {"properties": {"query": {"type": "string"}}}}
    text = '{"name": "web_search", "arguments": {"query": "cat fact"}}'
    assert find_call(text, tools) == TextCall("", "WebSearch", {"query": "cat fact"})
    assert find_call('{"name": "read", "arguments": {"path": "a"}}', tools) == TextCall(
        "", "Read", {"path": "a"}
    )
    both = {**tools, "web_search": {"properties": {}}, "Web-Search": {"properties": {}}}
    assert find_call('{"name": "websearch", "arguments": {}}', both) is None  # which one?


def test_a_call_in_qwen3_coders_form_is_found() -> None:
    # What qwen3-coder:30b on Ollama wrote on an eval task, ending its turn with nothing done.
    text = (
        "I'll convert the classes. Let me first examine the current implementation.\n\n"
        "<function=Read>\n<parameter=path>\nshipping/models.py\n</parameter>\n"
        "<parameter=offset>\n10\n</parameter>\n</function>\n</tool_call>"
    )

    assert find_call(text, TOOLS) == TextCall(
        "I'll convert the classes. Let me first examine the current implementation.",
        "Read",
        {"path": "shipping/models.py", "offset": 10},
    )


def test_qwen3_coder_values_are_read_as_their_schema_types() -> None:
    text = (
        "<tool_call>\n<function=Edits>\n"
        '<parameter=edits>\n[{"old": "a", "new": "b"}]\n</parameter>\n'
        "<parameter=all>\nTrue\n</parameter>\n"
        "<parameter=note>\n42\n</parameter>\n"
        "</function>\n</tool_call>"
    )

    call = find_call(text, TOOLS)

    assert call == TextCall(
        "", "Edits", {"edits": [{"old": "a", "new": "b"}], "all": True, "note": "42"}
    )


def test_a_string_keeps_its_inner_lines_and_indentation() -> None:
    body = "def f():\n    return 1\n"
    text = (
        "<function=Write>\n<parameter=path>\nf.py\n</parameter>\n"
        f"<parameter=content>\n{body}\n</parameter>\n</function>"
    )

    assert find_call(text, TOOLS) == TextCall("", "Write", {"path": "f.py", "content": body})


def test_whichever_form_comes_first_is_the_call() -> None:
    text = (
        '{"name": "Glob", "arguments": {"pattern": "*.py"}}\n'
        "<function=Read>\n<parameter=path>\na.py\n</parameter>\n</function>"
    )

    assert find_call(text, TOOLS) == TextCall("", "Glob", {"pattern": "*.py"})


@pytest.mark.parametrize(
    "text",
    [
        "<function=RunTests>\n</function>",  # not offered
        "<function=Read>\n<parameter=path>\na.py\n</parameter>\n",  # cut off
    ],
)
def test_qwen3_coder_text_that_isnt_a_whole_offered_call_stays_text(text: str) -> None:
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


def test_the_provider_sends_a_call_in_qwen3_coders_form_as_a_real_one() -> None:
    text = (
        "Writing it now.\n\n<function=Write>\n<parameter=path>\nout.txt\n</parameter>\n"
        "<parameter=content>\nhi\n</parameter>\n</function>\n</tool_call>"
    )
    server = Server(sse(*chunks(text), finish("stop")))

    response = stream_all(server.provider(), [user("Write hi to out.txt")])[-1]

    text_block, tool_block = response.content
    assert text_block == TextBlock(text="Writing it now.")
    assert isinstance(tool_block, ToolUseBlock)
    assert (tool_block.name, tool_block.input) == ("Write", {"path": "out.txt", "content": "hi"})
    assert response.stop_reason == "tool_use"
