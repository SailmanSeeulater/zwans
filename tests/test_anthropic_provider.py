from pydantic import BaseModel, Field

from zwans.messages import Message, RawBlock, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.anthropic import convert_content, message_param, tool_param
from zwans.tools.base import ToolContext, ToolOutput

THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}


def test_thinking_blocks_are_kept_verbatim_and_sent_back_unchanged() -> None:
    content = convert_content(
        [
            THINKING,
            {"type": "text", "text": "Running the tests."},
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest"}},
        ]
    )

    assert content == [
        RawBlock(type="thinking", data=THINKING),
        TextBlock(text="Running the tests."),
        ToolUseBlock(id="toolu_1", name="Bash", input={"command": "pytest"}),
    ]
    sent = message_param(Message(role="assistant", content=list(content)))
    assert sent["content"][0] == THINKING


def test_blocks_from_a_declined_attempt_keep_only_their_text() -> None:
    fallback = {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}}
    content = convert_content(
        [
            THINKING,
            {"type": "text", "text": "Partial answer"},
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}},
            fallback,
            {"type": "text", "text": "Answer from the fallback model"},
        ]
    )

    assert content == [
        TextBlock(text="Partial answer"),
        RawBlock(type="fallback", data=fallback),
        TextBlock(text="Answer from the fallback model"),
    ]


def test_tool_results_use_the_api_shape() -> None:
    message = Message(
        role="user", content=[ToolResultBlock(tool_use_id="toolu_1", content="ok", is_error=True)]
    )

    assert message_param(message) == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok", "is_error": True}
        ],
    }


class NoteInput(BaseModel):
    text: str = Field(description="What to note.")


class NoteTool:
    name = "Note"
    description = "Take a note."
    input_model = NoteInput
    read_only = True

    async def run(self, args: NoteInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content=args.text)


def test_tool_definitions_carry_the_schema_and_stream_their_input() -> None:
    param = tool_param(NoteTool())

    assert param["name"] == "Note"
    assert param["input_schema"]["properties"]["text"]["description"] == "What to note."
    assert param["eager_input_streaming"] is True
