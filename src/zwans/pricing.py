"""API prices, used to show what a turn and a session cost."""

from dataclasses import dataclass

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
    "claude-haiku-4-5": Price(input=1, output=5, cache_write=1.25, cache_read=0.10),
    "claude-fable-5-1": Price(input=10, output=50, cache_write=12.5, cache_read=0.25),
    # Models a refused request can fall back to.
    "claude-opus-5": Price(input=5, output=25, cache_write=6.25, cache_read=0.50),
    "claude-opus-4-8": Price(input=5, output=25, cache_write=6.25, cache_read=0.50),
}


def cost(usage: UsageUpdated) -> float | None:
    """Dollars for one model call, or None when the model's price isn't known."""
    price = PRICES.get(usage.model)
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
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.unpriced_models: set[str] = set()

    def on_event(self, event: Event) -> None:
        if isinstance(event, TurnStarted):
            self.turn_dollars = 0.0
        elif isinstance(event, UsageUpdated):
            self.input_tokens += event.input_tokens + event.cache_write_tokens
            self.output_tokens += event.output_tokens
            self.cache_read_tokens += event.cache_read_tokens
            dollars = cost(event)
            if dollars is None:
                self.unpriced_models.add(event.model or "unknown")
            else:
                self.turn_dollars += dollars
                self.session_dollars += dollars

    def summary(self) -> str:
        text = (
            f"${self.session_dollars:.4f} "
            f"({self.input_tokens:,} input, {self.cache_read_tokens:,} cached, "
            f"{self.output_tokens:,} output tokens)"
        )
        if self.unpriced_models:
            text += f"; no price known for {', '.join(sorted(self.unpriced_models))}"
        return text
