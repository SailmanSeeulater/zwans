"""Small helpers shared by the tests."""

import os
import time
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


def process_gone(pid: int, within: float = 5.0) -> bool:
    """Whether a process has ended (and been reaped) within a few seconds."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True  # the pid was reused by someone else's process
        time.sleep(0.05)
    return False
