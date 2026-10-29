"""API prices, used to show what a turn and a session cost."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from zwans.events import Event, TurnStarted, UsageUpdated


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float
    cache_write: float  # writing a 5-minute cache entry
    cache_read: float


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(input=4, output=20, cache_write=5, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2, output=10, cache_write=2.5, cache_read=0.20),
    # For prompts up to 100K tokens; longer ones cost 5x, which this doesn't model.
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_write=0.125, cache_read=0.01),
    "claude-haiku-4-5": Price(input=1, output=5, cache_write=1.25, cache_read=0.10),
    "claude-fable-5-1": Price(input=10, output=50, cache_write=12.5, cache_read=0.25),
    # Models a refused request can fall back to.
    "claude-opus-5": Price(input=5, output=25, cache_write=6.25, cache_read=0.50),
    "claude-opus-4-8": Price(input=5, output=25, cache_write=6.25, cache_read=0.50),
}


DATED_ID = re.compile(r"-\d{8}$")


def cost(usage: UsageUpdated) -> float | None:
    """Dollars for one model call, or None when the model's price isn't known."""
    # Older models answer with a dated ID, such as claude-haiku-4-5-20251001.
    price = PRICES.get(usage.model) or PRICES.get(DATED_ID.sub("", usage.model))
    if price is None:
        return None
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_write_tokens * price.cache_write
        + usage.cache_read_tokens * price.cache_read
    )
    return total / 1_000_000


class CostMeter:
    """Adds up tokens and dollars from the event stream, per turn and for the session."""

    def __init__(self) -> None:
        self.turn_dollars = 0.0
        self.session_dollars = 0.0
        self.input_tokens = 0  # sent at the full input price
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0
        self.output_tokens = 0
        self.unpriced_models: set[str] = set()

    def on_event(self, event: Event) -> None:
        if isinstance(event, TurnStarted):
            self.turn_dollars = 0.0
        elif isinstance(event, UsageUpdated):
            self.input_tokens += event.input_tokens
            self.cache_write_tokens += event.cache_write_tokens
            self.cache_read_tokens += event.cache_read_tokens
            self.output_tokens += event.output_tokens
            dollars = cost(event)
            if dollars is None:
                self.unpriced_models.add(event.model or "unknown")
            else:
                self.turn_dollars += dollars
                self.session_dollars += dollars

    def snapshot(self) -> dict[str, Any]:
        """The session totals, for saving."""
        return {
            "dollars": self.session_dollars,
            "input_tokens": self.input_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "output_tokens": self.output_tokens,
            "unpriced_models": sorted(self.unpriced_models),
        }

    @classmethod
    def restore(cls, saved: Mapping[str, Any]) -> Self:
        meter = cls()
        meter.session_dollars = float(saved.get("dollars", 0.0))
        meter.input_tokens = int(saved.get("input_tokens", 0))
        meter.cache_write_tokens = int(saved.get("cache_write_tokens", 0))
        meter.cache_read_tokens = int(saved.get("cache_read_tokens", 0))
        meter.output_tokens = int(saved.get("output_tokens", 0))
        meter.unpriced_models = set(saved.get("unpriced_models", []))
        return meter

    @property
    def sent_tokens(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def cache_hit_rate(self) -> float:
        """The share of input tokens that were read from the prompt cache."""
        return self.cache_read_tokens / self.sent_tokens if self.sent_tokens else 0.0

    def summary(self) -> str:
        text = (
            f"${self.session_dollars:.4f} ({self.sent_tokens:,} input tokens, "
            f"{self.cache_hit_rate:.0%} from cache; {self.output_tokens:,} output tokens)"
        )
        if self.unpriced_models:
            text += f"; no price known for {', '.join(sorted(self.unpriced_models))}"
        return text
