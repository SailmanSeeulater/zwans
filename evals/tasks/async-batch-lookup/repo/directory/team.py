"""The team page: one line per member."""

from directory.batch import lookup_many
from directory.client import UserClient


def format_member(username: str, profile: dict[str, str] | None) -> str:
    if profile is None:
        return f"{username}: (unknown user)"
    return f"{username}: {profile['name']}, {profile['title']}"


async def team_page(client: UserClient, team: str, usernames: list[str]) -> str:
    profiles = await lookup_many(client, usernames)
    lines = [f"Team {team} ({len(usernames)} members)"]
    for username, profile in zip(usernames, profiles, strict=True):
        lines.append("  " + format_member(username, profile))
    return "\n".join(lines)
