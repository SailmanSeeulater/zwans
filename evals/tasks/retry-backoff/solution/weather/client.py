"""WeatherClient turns the service's JSON into model objects."""

import time
from collections.abc import Callable
from datetime import date

from weather.models import Current, DayForecast
from weather.transport import Transport, TransportError


class CityNotFound(Exception):
    pass


class WeatherClient:
    def __init__(
        self,
        transport: Transport,
        *,
        retries: int = 3,
        backoff: float = 0.5,
        max_delay: float = 8.0,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self.transport = transport
        self.retries = retries
        self.backoff = backoff
        self.max_delay = max_delay
        self.sleep = sleep

    @staticmethod
    def _retryable(exc: TransportError) -> bool:
        return exc.status is None or exc.status == 429 or exc.status >= 500

    def _get_with_retries(self, path: str, params: dict[str, str]) -> object:
        attempt = 0
        while True:
            try:
                return self.transport.get_json(path, params)
            except TransportError as exc:
                if attempt >= self.retries or not self._retryable(exc):
                    raise
                attempt += 1
                self.sleep(min(self.backoff * 2 ** (attempt - 1), self.max_delay))

    def _get(self, path: str, params: dict[str, str]) -> object:
        try:
            return self._get_with_retries(path, params)
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
