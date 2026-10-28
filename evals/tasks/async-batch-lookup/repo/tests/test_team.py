import asyncio

from directory.batch import lookup_many
from directory.client import InMemoryUserClient
from directory.team import team_page

USERS = {
    "ada": {"name": "Ada Byron", "title": "Engineer"},
    "bo": {"name": "Bo Chen", "title": "Designer"},
    "cy": {"name": "Cy Okafor", "title": "Manager"},
}


def test_lookup_many() -> None:
    client = InMemoryUserClient(USERS)

    results = asyncio.run(lookup_many(client, ["cy", "ada"]))

    assert results == [USERS["cy"], USERS["ada"]]


def test_unknown_user_is_none() -> None:
    client = InMemoryUserClient(USERS)

    assert asyncio.run(lookup_many(client, ["zed"])) == [None]


def test_team_page() -> None:
    client = InMemoryUserClient(USERS)

    page = asyncio.run(team_page(client, "Core", ["ada", "bo", "nobody", "cy"]))

    assert page.splitlines() == [
        "Team Core (4 members)",
        "  ada: Ada Byron, Engineer",
        "  bo: Bo Chen, Designer",
        "  nobody: (unknown user)",
        "  cy: Cy Okafor, Manager",
    ]
