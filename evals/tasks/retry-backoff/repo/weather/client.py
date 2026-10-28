"""WeatherClient turns the service's JSON into model objects."""

from datetime import date

from weather.models import Current, DayForecast
from weather.transport import Transport, TransportError


class CityNotFound(Exception):
    pass


class WeatherClient:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    def _get(self, path: str, params: dict[str, str]) -> object:
        try:
            return self.transport.get_json(path, params)
        except TransportError as exc:
            if exc.status == 404:
                raise CityNotFound(params.get("city", "")) from exc
            raise

    def current(self, city: str) -> Current:
        data = self._get("/current", {"city": city})
        assert isinstance(data, dict)
        return Current(city=city, temperature=data["temp"], condition=data["condition"])

    def forecast(self, city: str, days: int = 3) -> list[DayForecast]:
        data = self._get("/forecast", {"city": city, "days": str(days)})
        assert isinstance(data, list)
        return [
            DayForecast(
                day=date.fromisoformat(item["date"]),
                low=item["low"],
                high=item["high"],
                condition=item["condition"],
            )
            for item in data
        ]
