"""Rough token counts, for deciding when to compact. The API's usage numbers are the real ones."""

from collections.abc import Sequence

from zwans.messages import ContentBlock, ImageBlock, Message, ToolResultBlock

CHARS_PER_TOKEN = 4  # a common rule of thumb for English text and code
IMAGE_TOKENS = 1_600  # about what a large image costs; the API scales bigger ones down
MESSAGE_CHARS = 20  # a message's own wrapping: its role and the JSON around its content


def approx_tokens(messages: Sequence[Message]) -> int:
    chars = sum(MESSAGE_CHARS + sum(map(block_chars, m.content)) for m in messages)
    return chars // CHARS_PER_TOKEN


def block_chars(block: ContentBlock) -> int:
    """A block's size in characters, counting an image as what it costs rather than as the
    length of its base64 text, which is far more."""
    if isinstance(block, ImageBlock):
        return IMAGE_TOKENS * CHARS_PER_TOKEN
    if isinstance(block, ToolResultBlock) and not isinstance(block.content, str):
        return MESSAGE_CHARS + sum(map(block_chars, block.content))
    return len(block.model_dump_json())
