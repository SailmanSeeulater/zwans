import pytest

from zwans.events import Event, TurnStarted, UsageUpdated
from zwans.pricing import CostMeter, cost


def test_cost_uses_the_price_of_the_model_that_answered() -> None:
    usage = UsageUpdated(
        model="claude-opus-5-5",
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_tokens=1_000_000,
    )

    assert cost(usage) == pytest.approx(4 + 2 + 0.20)


def test_unknown_models_have_no_price() -> None:
    assert cost(UsageUpdated(model="fake", input_tokens=10, output_tokens=10)) is None


def test_meter_tracks_the_turn_and_the_session() -> None:
    meter = CostMeter()
    call = UsageUpdated(model="claude-opus-5-5", input_tokens=500_000, output_tokens=0)

    events: list[Event] = [TurnStarted(), call, TurnStarted(), call]
    for event in events:
        meter.on_event(event)

    assert meter.turn_dollars == pytest.approx(2.0)
    assert meter.session_dollars == pytest.approx(4.0)
    assert meter.summary().startswith("$4.0000 (1,000,000 input")
