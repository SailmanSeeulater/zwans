"""A session's title, written by a model after its first turn: a few words saying what the
task is, in place of its first prompt cut short. One small request with no tools; a Claude
session asks Haiku, any other model asks itself (free on a local one)."""

import re

from zwans.messages import Message, TextBlock
from zwans.providers.base import ModelResponse, Provider

SYSTEM = (
    "You name coding sessions for a list of them. Reply with only the title: two to six "
    "words in sentence case saying what the task is, with no quotes and no full stop."
)
CHEAP_CLAUDE = "claude-haiku-5-5"
TITLE_CHARS = 60
PROMPT_CHARS = 2_000
REPLY_CHARS = 800
# What models wrap a title in: spaces, markdown, and straight or curly quotes.
QUOTES = " \t*_#`\"'\u201c\u201d\u2018\u2019"


def title_model(configured: str | None, session_model: str) -> str | None:
    """The model to ask: the configured one, else Haiku for a Claude session, else None for
    the session's own."""
    if configured:
        return configured
    return CHEAP_CLAUDE if session_model.startswith("claude-") else None


def clean_title(text: str) -> str:
    """The model's reply as a title: its first line, without quotes, a label, markdown or a
    full stop, and short. "" when nothing usable is left."""
    line = next((part.strip() for part in text.strip().splitlines() if part.strip()), "")
    line = re.sub(r"^(title|session)\s*:\s*", "", line, flags=re.IGNORECASE)
    line = line.strip(QUOTES).rstrip(".!:;,")
    line = " ".join(line.split())
    if len(line) > TITLE_CHARS:
        cut = line[: TITLE_CHARS - 1]
        line = (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(" ,.;:") + "…"
    return line


def request(prompt: str, reply: str) -> list[Message]:
    text = f"The task:\n{prompt.strip()[:PROMPT_CHARS]}"
    if reply.strip():
        text += f"\n\nThe start of the reply:\n{reply.strip()[:REPLY_CHARS]}"
    return [Message(role="user", content=[TextBlock(text=text)])]


async def write_title(
    provider: Provider, prompt: str, reply: str
) -> tuple[str, ModelResponse | None]:
    """Ask for a title. Returns it ("" when the reply had none) and the response, for its usage."""
    response: ModelResponse | None = None
    async for item in provider.stream(SYSTEM, request(prompt, reply), []):
        if isinstance(item, ModelResponse):
            response = item
    if response is None:
        return "", None
    said = "".join(block.text for block in response.content if isinstance(block, TextBlock))
    return clean_title(said), response
