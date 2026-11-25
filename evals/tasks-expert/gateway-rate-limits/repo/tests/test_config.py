import pytest

from tollgate import ConfigError, parse_config

GOOD = """
[gateway]
idle_after = 120
stats_key = "ops"

[plans.free]
limit = 3
window = 10

[plans.pro]
limit = 50
window = 2.5

[keys]
"k-a" = "free"
"k-b" = "pro"

[[routes]]
prefix = "/orders/"
upstream = "orders"
methods = ["get", "POST"]

[[routes]]
prefix = "/"
upstream = "web"
"""


def test_a_full_config() -> None:
    config = parse_config(GOOD)

    assert config.idle_after == 120
    assert config.stats_key == "ops"
    assert config.plans["pro"].limit == 50 and config.plans["pro"].window == 2.5
    assert config.plan_for("k-a").name == "free"
    assert config.plan_for("k-zzz") is None
    orders = config.routes[0]
    assert orders.prefix == "/orders"
    assert orders.allows("GET") and not orders.allows("DELETE")
    assert config.routes[1].allows("DELETE")


def test_defaults() -> None:
    config = parse_config("")

    assert config.idle_after == 3600
    assert config.stats_key is None
    assert config.routes == []


@pytest.mark.parametrize(
    "text",
    [
        "[plans.x]\nlimit = 0\nwindow = 1",
        "[plans.x]\nlimit = 2.5\nwindow = 1",
        "[plans.x]\nlimit = 2\nwindow = 0",
        "[plans.x]\nlimit = 2",
        "[keys]\nk = 'nope'",
        "[[routes]]\nprefix = 'orders'\nupstream = 'o'",
        "[[routes]]\nprefix = '/_stats'\nupstream = 'o'",
        "[[routes]]\nprefix = '/a'\nupstream = 'o'\n[[routes]]\nprefix = '/a/'\nupstream = 'p'",
        "[[routes]]\nprefix = '/a'\nupstream = 'o'\nmethods = ['FETCH']",
        "[gateway]\nidle_after = -1",
        "[gateway]\nstats_key = 'k'\n[plans.p]\nlimit = 1\nwindow = 1\n[keys]\nk = 'p'",
        "[surprise]\nx = 1",
        "not toml at all [",
    ],
)
def test_bad_configs_are_refused(text: str) -> None:
    with pytest.raises(ConfigError):
        parse_config(text)
