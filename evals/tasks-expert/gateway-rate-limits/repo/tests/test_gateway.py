import io

import pytest

from tollgate import ConfigError, Gateway, ManualClock, Request
from tollgate.cli import replay
from tollgate.upstreams import EchoUpstream, FailingUpstream

CONFIG = """
[gateway]
idle_after = 300
stats_key = "ops"

[plans.small]
limit = 3
window = 60

[plans.big]
limit = 5
window = 60

[keys]
"k-ann" = "small"
"k-bo" = "big"

[[routes]]
prefix = "/orders"
upstream = "orders"
methods = ["GET", "POST"]

[[routes]]
prefix = "/broken"
upstream = "down"

[[routes]]
prefix = "/ghost"
upstream = "nobody"
"""


def make(start: float = 1000.0) -> tuple[Gateway, ManualClock]:
    clock = ManualClock(start)
    upstreams = {"orders": EchoUpstream("orders"), "down": FailingUpstream()}
    return Gateway(CONFIG, upstreams, clock), clock


def get(gateway: Gateway, path: str, key: str | None = "k-ann", method: str = "GET"):
    headers = {} if key is None else {"X-Api-Key": key}
    return gateway.handle(Request(method, path, headers))


def test_a_request_goes_through_to_its_upstream() -> None:
    gateway, _ = make()

    response = get(gateway, "/orders/17")

    assert response.status == 200
    assert response.json() == {"upstream": "orders", "method": "GET", "path": "/orders/17"}


def test_keys_are_checked_before_routes() -> None:
    gateway, _ = make()

    assert get(gateway, "/orders", key=None).status == 401
    assert get(gateway, "/orders", key="k-who").status == 401
    assert get(gateway, "/nowhere").status == 404
    assert get(gateway, "/orders", method="DELETE").status == 405


def test_upstream_trouble_is_a_502() -> None:
    gateway, _ = make()

    assert get(gateway, "/broken").status == 502
    assert get(gateway, "/ghost").status == 502


def test_a_key_is_held_to_its_limit() -> None:
    gateway, clock = make()

    statuses = []
    for _ in range(5):
        statuses.append(get(gateway, "/orders").status)
        clock.advance(1)

    assert statuses == [200, 200, 200, 429, 429]
    assert get(gateway, "/orders", key="k-bo").status == 200  # keys don't share a limit


def test_a_throttled_request_says_when_to_retry() -> None:
    gateway, clock = make(start=600.0)
    for _ in range(3):
        get(gateway, "/orders")

    clock.advance(10.5)
    response = get(gateway, "/orders")

    assert response.status == 429
    assert response.headers["Retry-After"] == "50"


def test_requests_that_never_reach_the_limiter_dont_count() -> None:
    gateway, _ = make()
    for _ in range(10):
        get(gateway, "/nowhere")
        get(gateway, "/orders", method="DELETE")

    assert get(gateway, "/orders").status == 200


def test_stats() -> None:
    gateway, clock = make()
    for _ in range(4):
        get(gateway, "/orders")
        clock.advance(1)
    get(gateway, "/orders", key="k-bo")

    stats = get(gateway, "/_stats", key="ops")

    assert stats.status == 200
    assert stats.json() == {
        "keys": {
            "k-ann": {"plan": "small", "allowed": 3, "rejected": 1, "held": 3},
            "k-bo": {"plan": "big", "allowed": 1, "rejected": 0, "held": 1},
        }
    }
    assert get(gateway, "/_stats", key="k-ann").status == 404


def test_an_idle_key_is_forgotten() -> None:
    gateway, clock = make()
    get(gateway, "/orders")
    get(gateway, "/orders", key="k-bo")

    clock.advance(200)
    get(gateway, "/orders", key="k-bo")
    clock.advance(150)
    stats = get(gateway, "/_stats", key="ops").json()

    assert list(stats["keys"]) == ["k-bo"]


def test_reload_changes_routes_and_drops_removed_keys() -> None:
    gateway, _ = make()
    get(gateway, "/orders", key="k-bo")

    gateway.reload(CONFIG.replace('"k-bo" = "big"', "").replace('"/broken"', '"/fixed"'))

    assert get(gateway, "/orders", key="k-bo").status == 401
    assert get(gateway, "/broken").status == 404
    assert "k-bo" not in get(gateway, "/_stats", key="ops").json()["keys"]


def test_a_bad_reload_keeps_the_old_config() -> None:
    gateway, _ = make()

    with pytest.raises(ConfigError):
        gateway.reload("[plans.x]\nlimit = 0\nwindow = 1")

    assert get(gateway, "/orders").status == 200


def test_replaying_a_log() -> None:
    log = io.StringIO(
        "# reading key method path\n"
        "60 k-ann GET /orders\n"
        "61 k-ann GET /orders\n"
        "62 - GET /orders\n"
        "63 k-ann GET /orders/1\n"
        "64 k-ann POST /orders\n"
    )
    out = io.StringIO()

    counts = replay(CONFIG, log, out)

    assert counts == {200: 3, 401: 1, 429: 1}
    assert out.getvalue().splitlines()[-1] == "64 k-ann POST /orders -> 429 retry-after=56"
