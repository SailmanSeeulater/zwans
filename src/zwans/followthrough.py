"""Notices a reply that ends the turn with the work still to do.

A chat API ends the turn when a reply has no tool call. Small models often write "I will now
rename the function" or show the new code in the reply, and stop there: the turn is over and
nothing was changed. This spots those two endings, so the loop can send the model back once
or twice to do what it said (the `follow_through` setting). It reads only the reply's text,
so it can be wrong; the note it sends says what to do if the task is in fact finished.
"""

import re
from collections.abc import Callable

from zwans.config import Config
from zwans.providers.base import Provider

# Saying what comes next: "I will now ...", "Let me ...", "Next, I'll ...".
INTENT = re.compile(
    r"\b(?:i\s+will|i'll|i\s+am\s+going\s+to|i'm\s+going\s+to|let\s+me|let's|let\s+us"
    r"|now,?\s+i|next,?\s+i|proceed(?:ing)?\s+(?:to|by|with))\b",
    re.IGNORECASE,
)
# The same words, said to the user rather than about the next step.
OFFER = re.compile(
    r"\blet\s+me\s+know\b|\bif\s+you\b|\bwould\s+you\s+like\b|\bwant\s+me\s+to\b|\bfeel\s+free\b",
    re.IGNORECASE,
)
CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
# A reply that stops on the tag that should open a call: "<tool_request>", "<tool_call>".
OPEN_TAG = re.compile(r"<(?:tool|function)[_ a-z]*>\s*\Z", re.IGNORECASE)
TAIL_SENTENCES = 2  # how much of the end of the reply counts as how it ended
MIN_CODE_LINES = 3  # a shorter block is an example or a command, not the change itself
LOCAL_FOLLOW_THROUGH = 2  # times a turn sends a local model back to finish what it announced

ANNOUNCED = (
    "You ended your turn after saying what you would do next, without doing it. Nobody has "
    "replied: you are still working on the same task. If it isn't finished, carry on now by "
    "calling the tool for that step. If it is finished, say so in one line."
)
ONLY_SHOWN = (
    "You showed code in your reply but changed no file this turn, so nothing has been done "
    "yet. If the task asks for a change, make it now with Edit or Write, then check it. If "
    "it only asked for an explanation, say you're done in one line."
)


def announces_a_step(text: str) -> bool:
    """Whether the reply ends by saying what the model is about to do."""
    if OPEN_TAG.search(text):
        return True
    without_code = CODE_BLOCK.sub(" ", text).strip()
    if not without_code or without_code.endswith("?"):
        return False  # a question hands the turn to the user, which is right
    sentences = [s for s in re.split(r"(?<=[.!:])\s+|\n+", without_code) if s.strip()]
    for sentence in sentences[-TAIL_SENTENCES:]:
        if INTENT.search(sentence) and not OFFER.search(sentence):
            return True
    return False


def only_shows_code(text: str) -> bool:
    """Whether the reply holds a block of code long enough to be the change itself."""
    return any(
        len(block.strip().splitlines()) >= MIN_CODE_LINES for block in CODE_BLOCK.findall(text)
    )


def unfinished(text: str, changed: bool) -> str | None:
    """What to tell a model whose final reply left the work undone, or None when the reply
    reads as finished. `changed` is whether a tool that can change files ran this turn."""
    if announces_a_step(text):
        return ANNOUNCED
    if not changed and only_shows_code(text):
        return ONLY_SHOWN
    return None


def follow_through_for(config: Config, provider: Provider) -> Callable[[], int]:
    """How many times a turn may send the model back to do what its final reply only
    announced: the `follow_through` setting, or, unset, LOCAL_FOLLOW_THROUGH for a model on
    a local server and 0 for any other. Asked each turn, as /model can switch between them."""

    def count() -> int:
        if config.follow_through is not None:
            return config.follow_through
        info = getattr(getattr(provider, "resolved", None), "info", None)
        return LOCAL_FOLLOW_THROUGH if info is not None and info.local else 0

    return count
