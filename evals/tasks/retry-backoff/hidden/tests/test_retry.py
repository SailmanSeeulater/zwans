import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakes import FakeTransport

from weather.client import CityNotFound, WeatherClient
from weather.models import Current
from weather.transport import TransportError

GOOD = {"temp": 20.0, "condition": "sun"}


def down() -> TransportError:
    return TransportError("connection refused")


def status(code: int) -> TransportError:
    return TransportError(f"HTTP {code}", status=code)


def make(transport: FakeTransport, **options: object) -> tuple[WeatherClient, list[float]]:
    sleeps: list[float] = []
    client = WeatherClient(transport, sleep=sleeps.append, **options)  # type: ignore[arg-type]
    return client, sleeps


def test_defaults() -> None:
    transport = FakeTransport(down(), status(503), status(429), GOOD)
    client, sleeps = make(transport)

    assert client.current("Ghent") == Current("Ghent", 20.0, "sun")
    assert sleeps == [0.5, 1.0, 2.0]
    assert len(transport.calls) == 4


def test_gives_up_and_raises_the_last_error() -> None:
    last = status(502)
    transport = FakeTransport(down(), status(500), status(503), last)
    client, sleeps = make(transport)

    with pytest.raises(TransportError) as caught:
        client.current("Ghent")

    assert caught.value is last
    assert sleeps == [0.5, 1.0, 2.0]
    assert len(transport.calls) == 4


def test_no_retries() -> None:
    transport = FakeTransport(down())
    client, sleeps = make(transport, retries=0)

    with pytest.raises(TransportError):
        client.current("Ghent")

    assert sleeps == []
    assert len(transport.calls) == 1


def test_backoff_is_capped() -> None:
    transport = FakeTransport(*[down() for _ in range(6)], GOOD)
    client, sleeps = make(transport, retries=6, backoff=1.0, max_delay=5.0)

    client.current("Ghent")

    assert sleeps == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0]


def test_custom_backoff() -> None:
    transport = FakeTransport(status(500), status(500), GOOD)
    client, sleeps = make(transport, retries=5, backoff=0.1)

    client.current("Ghent")

    assert sleeps == pytest.approx([0.1, 0.2])


@pytest.mark.parametrize("code", [400, 401, 403, 422])
def test_client_errors_are_not_retried(code: int) -> None:
    transport = FakeTransport(status(code), GOOD)
    client, sleeps = make(transport)

    with pytest.raises(TransportError) as caught:
        client.current("Ghent")

    assert caught.value.status == code
    assert sleeps == []
    assert len(transport.calls) == 1


def test_not_found_is_not_retried() -> None:
    transport = FakeTransport(status(404), GOOD)
    client, sleeps = make(transport)

    with pytest.raises(CityNotFound):
        client.current("Atlantis")

    assert sleeps == []


def test_not_found_after_a_retry() -> None:
    transport = FakeTransport(status(503), status(404))
    client, sleeps = make(transport)

    with pytest.raises(CityNotFound):
        client.current("Atlantis")

    assert sleeps == [0.5]


def test_forecast_retries_too() -> None:
    day = {"date": "2024-05-01", "low": 8, "high": 17, "condition": "sun"}
    transport = FakeTransport(down(), [day])
    client, sleeps = make(transport)

    assert len(client.forecast("Ghent", days=1)) == 1
    assert sleeps == [0.5]
    assert transport.calls[0] == transport.calls[1]


def test_options_are_keyword_only() -> None:
    with pytest.raises(TypeError):
        WeatherClient(FakeTransport(), 3)  # type: ignore[misc]

