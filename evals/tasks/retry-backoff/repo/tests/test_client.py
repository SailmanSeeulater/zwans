import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakes import FakeTransport

from weather.client import CityNotFound, WeatherClient
from weather.models import Current, DayForecast
from weather.transport import TransportError


def test_current() -> None:
    transport = FakeTransport({"temp": 12.5, "condition": "rain"})

    result = WeatherClient(transport).current("Ghent")

    assert result == Current(city="Ghent", temperature=12.5, condition="rain")
    assert transport.calls == [("/current", {"city": "Ghent"})]


def test_forecast() -> None:
    transport = FakeTransport(
        [
            {"date": "2024-05-01", "low": 8, "high": 17, "condition": "sun"},
            {"date": "2024-05-02", "low": 9, "high": 15, "condition": "cloud"},
        ]
    )

    result = WeatherClient(transport).forecast("Ghent", days=2)

    assert result[1] == DayForecast(date(2024, 5, 2), 9, 15, "cloud")
    assert transport.calls == [("/forecast", {"city": "Ghent", "days": "2"})]


def test_unknown_city() -> None:
    transport = FakeTransport(TransportError("not found", status=404))

    with pytest.raises(CityNotFound):
        WeatherClient(transport).current("Atlantis")
