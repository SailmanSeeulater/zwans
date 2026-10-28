"""Look up many users at once without flooding the directory service."""

import asyncio

from directory.client import UserClient, UserNotFound

DEFAULT_LIMIT = 5


async def lookup_many(
    client: UserClient, usernames: list[str], limit: int = DEFAULT_LIMIT
) -> list[dict[str, str] | None]:
    """Fetch every user, at most `limit` requests at a time.

    Returns one result per username, in the same order as `usernames`; None for a
    username the directory doesn't know.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    semaphore = asyncio.Semaphore(limit)

    async def fetch_one(username: str) -> dict[str, str] | None:
        async with semaphore:
            try:
                return await client.fetch(username)
            except UserNotFound:
                return None

    tasks = [asyncio.create_task(fetch_one(name)) for name in usernames]
    results = []
    for next_done in asyncio.as_completed(tasks):
        results.append(await next_done)
    return results
