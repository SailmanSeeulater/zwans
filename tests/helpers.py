"""Small helpers shared by the tests."""

from collections.abc import AsyncIterator, Callable

import pytest

from zwans.events import Event
from zwans.executor.local import find_bash, find_program
from zwans.messages import Message, TextBlock


async def collect(events: AsyncIterator[Event]) -> list[Event]:
    return [event async for event in events]


def user(text: str) -> Message:
    return Message(role="user", content=[TextBlock(text=text)])


def _available(find: Callable[[], str]) -> bool:
    try:
        find()
    except FileNotFoundError:
        return False
    return True


needs_rg = pytest.mark.skipif(
    not _available(lambda: find_program("rg")), reason="ripgrep is not installed"
)
needs_bash = pytest.mark.skipif(not _available(find_bash), reason="bash is not installed")
