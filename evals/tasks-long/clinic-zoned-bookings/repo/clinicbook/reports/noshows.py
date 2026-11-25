"""No-show rates by clinician and month."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .. import formatting
from ..repository import Repository
from ..storage import Store


@dataclass
class NoShowLine:
    clinician: str
    month: str  # YYYY-MM
    seen: int
    no_shows: int

    @property
    def rate(self) -> float:
        total = self.seen + self.no_shows
        return round(100 * self.no_shows / total, 1) if total else 0.0


def no_show_summary(store: Store, clinic_id: str | None = None) -> list[NoShowLine]:
    repo = Repository(store)
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for appt in repo.appointments(clinic=clinic_id):
        if appt.status not in ("completed", "no_show"):
            continue
        key = (appt.clinician, appt.start.strftime("%Y-%m"))
        counts[key][0 if appt.status == "completed" else 1] += 1
    return [
        NoShowLine(clinician, month, seen, missed)
        for (clinician, month), (seen, missed) in sorted(counts.items())
    ]


def render(lines: list[NoShowLine]) -> str:
    return formatting.table(
        ["clinician", "month", "seen", "no-shows", "rate"],
        [[ln.clinician, ln.month, ln.seen, ln.no_shows, f"{ln.rate}%"] for ln in lines],
    ) + "\n"
