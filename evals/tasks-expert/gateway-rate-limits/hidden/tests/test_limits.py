"""The rate limiter against the README: a sliding window with its boundary rule, rejected
requests not counting, at most `limit` times kept per key, the gateway's own time when the
clock steps back, reloads that keep history, and idle keys forgotten on time."""

import random

import pytest
from oracle import Model, Setup

from tollgate import Gateway, ManualClock, Request
from tollgate.upstreams import EchoUpstream


def build(setup: Setup, start: float) -> tuple[Gateway, ManualClock]:
    clock = ManualClock(start)
    return Gateway(setup.toml(), {"api": EchoUpstream("api")}, clock), clock


def call(gateway: Gateway, key: str | None, path: str = "/api/things", method: str = "GET"):
    headers = {} if key is None else {"X-Api-Key": key}
    return gateway.handle(Request(method, path, headers))


def status(gateway: Gateway, key: str | None = "k1") -> int:
    return call(gateway, key).status


def stats(gateway: Gateway) -> dict:
    response = call(gateway, "ops", "/_stats")
    assert response.status == 200
    return response.json()["keys"]


def one_key(limit: int, window: float, idle_after: float = 10_000.0) -> Setup:
    return Setup({"p": (limit, window)}, {"k1": "p"}, idle_after)


# -- the window


def test_a_burst_across_a_period_boundary_is_still_one_window() -> None:
    gateway, clock = build(one_key(3, 10), start=9.5)
    first = [status(gateway) for _ in range(3)]
    clock.set(10.5)
    second = [status(gateway) for _ in range(3)]

    assert first == [200, 200, 200]
    assert second == [429, 429, 429]


def test_a_request_exactly_one_window_later_no_longer_sees_the_old_one() -> None:
    gateway, clock = build(one_key(2, 10), start=100)
    assert [status(gateway), status(gateway)] == [200, 200]

    clock.set(109.75)
    response = call(gateway, "k1")
    assert response.status == 429
    assert response.headers["Retry-After"] == "1"

    clock.set(110)
    assert status(gateway) == 200
    assert status(gateway) == 200
    assert status(gateway) == 429


def test_retry_after_counts_to_the_oldest_kept_request_leaving() -> None:
    gateway, clock = build(one_key(3, 30), start=0)
    for at in (0, 4, 9):
        clock.set(at)
        assert status(gateway) == 200

    clock.set(12.5)
    response = call(gateway, "k1")

    assert response.status == 429
    assert response.headers["Retry-After"] == "18"  # 0 leaves at 30


def test_rejected_requests_dont_count() -> None:
    gateway, clock = build(one_key(2, 10), start=0)
    assert [status(gateway), status(gateway)] == [200, 200]

    for step in range(1, 40):
        clock.set(step * 0.25)
        assert status(gateway) == 429

    clock.set(10)
    assert status(gateway) == 200


# -- memory


def test_a_busy_key_keeps_at_most_its_limit() -> None:
    gateway, clock = build(one_key(5, 2), start=0)
    for step in range(4000):
        clock.set(step * 0.125)
        status(gateway)

    assert stats(gateway)["k1"]["held"] <= 5


def test_kept_times_are_not_dropped_for_leaving_the_window() -> None:
    gateway, clock = build(one_key(4, 5), start=0)
    for at in (0, 1, 2):
        clock.set(at)
        status(gateway)

    clock.set(500)
    assert stats(gateway)["k1"]["held"] == 3


# -- time


def test_a_clock_stepped_back_an_hour_costs_nobody_an_hour() -> None:
    gateway, clock = build(one_key(3, 10), start=50_000)
    for _ in range(3):
        status(gateway)
    assert status(gateway) == 429

    clock.set(50_000 - 3600)
    response = call(gateway, "k1")
    assert response.status == 429
    assert response.headers["Retry-After"] == "10"

    clock.set(50_000 - 3600 + 10)
    assert status(gateway) == 200


def test_across_a_backward_step_no_time_passes() -> None:
    gateway, clock = build(one_key(1, 10), start=100)
    assert status(gateway) == 200

    clock.set(50)  # the gateway's time stays at 100
    response = call(gateway, "k1")
    assert (response.status, response.headers["Retry-After"]) == (429, "10")

    clock.set(55)  # 105
    response = call(gateway, "k1")
    assert (response.status, response.headers["Retry-After"]) == (429, "5")

    clock.set(60)  # 110
    assert status(gateway) == 200


def test_a_clock_that_steps_back_does_not_freeze_the_gateway() -> None:
    gateway, clock = build(one_key(2, 4), start=1000)
    assert [status(gateway), status(gateway)] == [200, 200]

    clock.set(900)
    for reading in (901, 902, 903, 904):  # the gateway sees 1000, 1001, 1002, 1003
        clock.set(reading)
        assert status(gateway) == 429
    clock.set(905)

    assert status(gateway) == 200


# -- reloading


def test_a_reload_keeps_history_under_the_new_window() -> None:
    setup = one_key(3, 10)
    gateway, clock = build(setup, start=0)
    for _ in range(3):
        status(gateway)

    gateway.reload(one_key(3, 60).toml())
    clock.set(30)

    assert status(gateway) == 429


def test_a_reload_that_lowers_the_limit_drops_the_oldest_at_once() -> None:
    gateway, clock = build(one_key(5, 100), start=0)
    for at in range(5):
        clock.set(at)
        status(gateway)

    gateway.reload(one_key(2, 100).toml())

    assert stats(gateway)["k1"]["held"] == 2
    clock.set(102)
    assert status(gateway) == 429  # 3 and 4 are kept, and still in the window
    clock.set(103)
    assert status(gateway) == 200


def test_a_reload_that_raises_the_limit_brings_nothing_back() -> None:
    gateway, clock = build(one_key(2, 10), start=0)
    for at in (0, 1, 10):
        clock.set(at)
        assert status(gateway) == 200  # at 10, the time 0 is pushed out

    gateway.reload(one_key(3, 100).toml())
    clock.set(11)

    assert status(gateway) == 200
    assert status(gateway) == 429


def test_a_reload_that_widens_the_window_still_sees_old_kept_times() -> None:
    gateway, clock = build(one_key(2, 5), start=0)
    for at in (0, 1, 20):
        clock.set(at)
        assert status(gateway) == 200  # kept: 1 and 20

    gateway.reload(one_key(2, 100).toml())
    clock.set(21)

    assert status(gateway) == 429


# -- idle keys


def test_a_throttled_key_is_still_active() -> None:
    gateway, clock = build(one_key(1, 1000, idle_after=50), start=0)
    assert status(gateway) == 200
    for at in (40, 80, 120):
        clock.set(at)
        assert status(gateway) == 429


def test_requests_that_never_reach_the_limiter_dont_keep_a_key_active() -> None:
    gateway, clock = build(one_key(1, 1000, idle_after=50), start=0)
    assert status(gateway) == 200
    clock.set(40)
    assert call(gateway, "k1", "/nowhere").status == 404

    clock.set(50)  # exactly idle_after since the last request that reached the limiter

    assert stats(gateway) == {}
    assert status(gateway) == 200


# -- any stream of requests


PLANS = [(1, 1.0), (2, 2.5), (3, 4.0), (3, 10.0), (4, 7.5), (5, 20.0), (2, 0.5)]
FORWARD = [0.0, 0.0, 0.125, 0.125, 0.25, 0.375, 0.5, 0.75, 1.0, 1.5, 2.5, 4.0, 7.25]
BACKWARD = [0.25, 0.5, 2.0, 6.5, 30.0, 400.0]


def random_setup(rng: random.Random) -> Setup:
    plans = {f"p{index}": rng.choice(PLANS) for index in range(3)}
    keys = {f"k{index}": rng.choice(list(plans)) for index in range(1, 5) if rng.random() < 0.9}
    keys.setdefault("k1", "p0")
    return Setup(plans, keys, rng.choice([6.0, 15.0, 40.0, 100_000.0]))


@pytest.mark.parametrize("seed", range(250))
def test_any_request_stream_matches_the_readme(seed: int) -> None:
    rng = random.Random(seed)
    setup = random_setup(rng)
    reading = float(rng.randrange(0, 100_000)) / 8
    gateway, clock = build(setup, start=reading)
    model = Model(setup)
    trail: list[str] = []

    for step in range(160):
        roll = rng.random()
        if roll < 0.06:
            reading -= rng.choice(BACKWARD)
        elif roll < 0.1:
            reading += rng.choice([20.0, 45.5, 120.0])
        else:
            reading += rng.choice(FORWARD)
        clock.set(reading)

        roll = rng.random()
        if roll < 0.04:
            setup = random_setup(rng)
            gateway.reload(setup.toml())
            model.reload(setup)
            trail.append(f"reload {setup}")
            continue
        if roll < 0.12:
            trail.append(f"{reading}: stats")
            got = stats(gateway)
            want = model.stats(reading)["keys"]
            assert got == want, f"seed {seed}, step {step}: stats {got} should be {want}.\n" + "\n".join(trail[-25:])
            continue

        key = rng.choice(["k1", "k1", "k2", "k2", "k3", "k4", "k9", None])
        path, method, known = "/api/x", "GET", None
        if rng.random() < 0.08:
            path, method, known = rng.choice([("/nope", "GET", 404), ("/admin", "POST", 405)])
        response = call(gateway, key, path, method)
        want_status, want_retry = model.request(reading, key, known)
        got_retry = response.headers.get("Retry-After")
        trail.append(f"{reading}: {key} {method} {path} -> {response.status} {got_retry}")
        assert response.status == want_status, (
            f"seed {seed}, step {step}: {key} {method} {path} at clock {reading} got "
            f"{response.status}, should be {want_status}.\n" + "\n".join(trail[-25:])
        )
        if want_status == 429:
            assert got_retry == str(want_retry), (
                f"seed {seed}, step {step}: Retry-After {got_retry}, should be {want_retry}.\n"
                + "\n".join(trail[-25:])
            )
