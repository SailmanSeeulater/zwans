from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Current:
    city: str
    temperature: float
    condition: str


@dataclass(frozen=True)
class DayForecast:
    day: date
    low: float
    high: float
    condition: str
