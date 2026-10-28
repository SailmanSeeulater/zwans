"""Clients for the user directory service."""

import asyncio
from typing import Protocol


class UserNotFound(Exception):
    pass


class UserClient(Protocol):
    async def fetch(self, username: str) -> dict[str, str]:
        """The user's profile: at least "name" and "title". Raises UserNotFound."""
        ...


class InMemoryUserClient:
    """A stand-in for the directory service, for local runs and tests."""

    def __init__(self, users: dict[str, dict[str, str]], delay: float = 0.0) -> None:
        self.users = users
        self.delay = delay
        self.calls: list[str] = []

    async def fetch(self, username: str) -> dict[str, str]:
        self.calls.append(username)
        await asyncio.sleep(self.delay)
        try:
            return dict(self.users[username])
        except KeyError:
            raise UserNotFound(username) from None
