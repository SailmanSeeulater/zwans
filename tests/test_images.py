import asyncio
import base64
from pathlib import Path
from typing import Any

import pytest

from zwans.context.tokens import IMAGE_TOKENS, approx_tokens
from zwans.images import MAX_IMAGE_BYTES, ImageError, describe, image_block, media_type
from zwans.messages import ImageBlock, Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.anthropic import message_param, without_image_data
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.store import SessionInfo, SessionStore
from zwans.tools.base import ToolContext, ToolError
from zwans.tools.read import ReadInput, ReadTool

# A 1200x800 PNG's signature and IHDR chunk: enough to be recognized and measured.
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x04\xb0\x00\x00\x03\x20" + b"\x00" * 64


def test_images_are_recognized_by_their_bytes_not_their_names() -> None:
    assert media_type(PNG) == "image/png"
    assert media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert media_type(b"GIF89a\x02\x00\x03\x00") == "image/gif"
    assert media_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert media_type(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert describe(PNG) == "PNG image, 1200x800, 1 KB"
    assert describe(b"GIF89a\x02\x00\x03\x00") == "GIF image, 2x3, 1 KB"


def test_image_blocks_carry_base64_and_refuse_what_the_api_wont_take() -> None:
    block = image_block(PNG, "shot.png")

    assert block.source.media_type == "image/png"
    assert base64.b64decode(block.source.data) == PNG
    with pytest.raises(ImageError, match="isn't a PNG"):
        image_block(b"plain text", "notes.txt")
    with pytest.raises(ImageError, match="Make a smaller copy"):
        image_block(PNG + b"\x00" * MAX_IMAGE_BYTES, "huge.png")


def test_read_shows_the_model_an_image(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "shot.png").write_bytes(PNG)

    output = asyncio.run(ReadTool().run(ReadInput(path="shot.png"), ctx))

    assert output.content == "shot.png: PNG image, 1200x800, 1 KB"
    assert [image.source.media_type for image in output.images] == ["image/png"]


def test_read_refuses_an_image_too_big_to_send(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "huge.png").write_bytes(PNG + b"\x00" * MAX_IMAGE_BYTES)

    with pytest.raises(ToolError, match="Make a smaller copy"):
        asyncio.run(ReadTool().run(ReadInput(path="huge.png"), ctx))


def test_an_image_from_a_tool_goes_back_inside_its_result(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "shot.png").write_bytes(PNG)
    provider = FakeProvider(
        [
            ModelResponse(
                content=[ToolUseBlock(id="t1", name="Read", input={"path": "shot.png"})],
                stop_reason="tool_use",
            ),
            ModelResponse(content=[TextBlock(text="A blank image.")], stop_reason="end_turn"),
        ]
    )
    session = Session(provider, [ReadTool()], ctx, "You are Zwans.", listeners=[])

    asyncio.run(session.send("What's in shot.png?"))

    result = session.messages[2].content[0]
    assert isinstance(result, ToolResultBlock) and isinstance(result.content, list)
    assert isinstance(result.content[0], TextBlock) and isinstance(result.content[1], ImageBlock)
    assert result.text() == "shot.png: PNG image, 1200x800, 1 KB\n[image]"


def test_images_in_messages_take_the_api_shape_and_survive_a_save(tmp_path: Path) -> None:
    image = image_block(PNG, "shot.png")
    messages = [
        Message(role="user", content=[image, TextBlock(text="What's this?")]),
        Message(
            role="user",
            content=[ToolResultBlock(tool_use_id="t1", content=[TextBlock(text="ok"), image])],
        ),
    ]
    store = SessionStore(tmp_path / "sessions.db")
    store.create(SessionInfo(id="s1", workspace="/work", model="m", system="s"))
    store.append_messages("s1", 0, messages)

    assert store.load_messages("s1") == messages
    store.close()
    source = {"type": "base64", "media_type": "image/png", "data": image.source.data}
    assert message_param(messages[1])["content"][0]["content"] == [
        {"type": "text", "text": "ok"},
        {"type": "image", "source": source},
    ]


def test_images_count_as_a_fixed_number_of_tokens() -> None:
    image = image_block(PNG, "shot.png")
    text_only = approx_tokens([Message(role="user", content=[TextBlock(text="hi")])])
    with_image = approx_tokens([Message(role="user", content=[image, TextBlock(text="hi")])])

    assert with_image - text_only == IMAGE_TOKENS


def test_the_inspector_copy_of_a_request_leaves_out_image_data() -> None:
    data = base64.b64encode(PNG).decode()
    request: dict[str, Any] = {
        "messages": [{"content": [{"type": "image", "source": {"type": "base64", "data": data}}]}]
    }

    shown = without_image_data(request)

    assert (
        shown["messages"][0]["content"][0]["source"]["data"]
        == f"<{len(data)} characters of base64>"
    )
    assert request["messages"][0]["content"][0]["source"]["data"] == data  # the original is kept
