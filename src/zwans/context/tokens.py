"""Rough token counts, for deciding when to compact. The API's usage numbers are the real ones."""

from collections.abc import Sequence

from zwans.messages import Message

CHARS_PER_TOKEN = 4  # a common rule of thumb for English text and code


def approx_tokens(messages: Sequence[Message]) -> int:
    return sum(len(message.model_dump_json()) for message in messages) // CHARS_PER_TOKEN
