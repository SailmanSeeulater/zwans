"""A spending cap for a session: once what it has cost reaches the cap, the next model call
doesn't happen and the turn ends with stop_reason "budget". The check comes before each
call, so the call that crosses the cap still finishes; a session goes over by at most one
call's cost. Raising the cap, or clearing it, lets the session carry on."""

from dataclasses import dataclass

from zwans.pricing import CostMeter


def parse_dollars(text: str) -> float | None:
    """ "$2", "2", "0.50" -> dollars; "off", "none" or "" -> None (no cap). Raises ValueError."""
    cleaned = text.strip().lower().lstrip("$").strip()
    if cleaned in ("", "off", "none", "no"):
        return None
    dollars = float(cleaned)
    if dollars < 0 or dollars != dollars:  # NaN isn't equal to itself
        raise ValueError(f"{text} isn't an amount of dollars.")
    return dollars


@dataclass
class Budget:
    meter: CostMeter
    dollars: float | None = None  # the most the session may cost, in all; None is no cap

    @property
    def spent(self) -> float:
        return self.meter.session_dollars

    def left(self) -> float | None:
        return None if self.dollars is None else max(0.0, self.dollars - self.spent)

    def exceeded(self) -> str | None:
        """Why the next model call mustn't happen, or None while there's money left."""
        if self.dollars is None or self.spent < self.dollars:
            return None
        return f"${self.spent:.2f} of the ${self.dollars:.2f} budget spent"

    def describe(self) -> str:
        if self.dollars is None:
            return f"No budget; ${self.spent:.4f} spent so far."
        return f"${self.spent:.2f} of ${self.dollars:.2f} spent, ${self.left():.2f} left."
