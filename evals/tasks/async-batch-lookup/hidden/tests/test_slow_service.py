import asyncio

import pytest

from directory.batch import lookup_many
from directory.client import UserNotFound
from directory.team import team_page


class SlowClient:
    """Answers each user after its own delay, and records how many calls overlap."""

    def __init__(self, users: dict[str, dict[str, str]], delays: dict[str, float]) -> None:
        self.users = users
        self.delays = delays
        self.in_flight = 0
        self.most_in_flight = 0

    async def fetch(self, username: str) -> dict[str, str]:
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delays.get(username, 0.0))
            if username not in self.users:
                raise UserNotFound(username)
            return dict(self.users[username])
        finally:
            self.in_flight -= 1


def people(count: int) -> dict[str, dict[str, str]]:
    return {f"u{n}": {"name": f"Person {n}", "title": f"Title {n}"} for n in range(count)}


def test_results_follow_the_input_order_when_answers_arrive_backwards() -> None:
    users = people(6)
    names = list(users)
    client = SlowClient(users, {name: 0.06 - 0.01 * i for i, name in enumerate(names)})

    results = asyncio.run(lookup_many(client, names, limit=6))

    assert results == [users[name] for name in names]


def test_missing_users_keep_their_place() -> None:
    users = people(4)
    names = ["u0", "ghost", "u1", "u2", "nobody", "u3"]
    delays = {"u0": 0.05, "ghost": 0.0, "u1": 0.03, "u2": 0.0, "nobody": 0.04, "u3": 0.01}
    client = SlowClient(users, delays)

    results = asyncio.run(lookup_many(client, names, limit=3))

    assert results == [users["u0"], None, users["u1"], users["u2"], None, users["u3"]]


def test_duplicates_each_get_a_result() -> None:
    users = people(2)
    client = SlowClient(users, {"u0": 0.03, "u1": 0.0})

    results = asyncio.run(lookup_many(client, ["u0", "u1", "u0", "u1"], limit=4))

    assert results == [users["u0"], users["u1"], users["u0"], users["u1"]]


def test_team_page_with_a_slow_service() -> None:
    users = {
        "ada": {"name": "Ada Byron", "title": "Engineer"},
        "bo": {"name": "Bo Chen", "title": "Designer"},
        "cy": {"name": "Cy Okafor", "title": "Manager"},
    }
    client = SlowClient(users, {"ada": 0.05, "bo": 0.03, "cy": 0.0})

    page = asyncio.run(team_page(client, "Core", ["ada", "bo", "nobody", "cy"]))

    assert page.splitlines() == [
        "Team Core (4 members)",
        "  ada: Ada Byron, Engineer",
        "  bo: Bo Chen, Designer",
        "  nobody: (unknown user)",
        "  cy: Cy Okafor, Manager",
    ]


@pytest.mark.parametrize("limit", [1, 3, 5])
def test_requests_overlap_up_to_the_limit(limit: int) -> None:
    users = people(12)
    client = SlowClient(users, {name: 0.01 * (n % 4 + 1) for n, name in enumerate(users)})

    results = asyncio.run(lookup_many(client, list(users), limit=limit))

    assert results == list(users.values())
    assert client.most_in_flight == limit


def test_empty() -> None:
    assert asyncio.run(lookup_many(SlowClient({}, {}), [])) == []


def test_limit_must_be_positive() -> None:
    with pytest.raises(ValueError):
        asyncio.run(lookup_many(SlowClient({}, {}), ["a"], limit=0))
