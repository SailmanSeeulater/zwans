"""Room utilisation: booked minutes against open minutes, room by room, day by day."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .. import formatting
from ..errors import ValidationError
from ..repository import Repository
from ..storage import Store
from ..timeutil import date_range, format_date, local_midnight

COUNTED = ("booked", "completed", "no_show")


@dataclass
class Utilisation:
    clinic: str
    first: date
    last: date
    open_minutes: dict[date, int] = field(default_factory=dict)
    booked: dict[str, dict[date, int]] = field(default_factory=dict)  # room -> day -> minutes

    def percent(self, room: str, day: date) -> float:
        available = self.open_minutes.get(day, 0)
        if not available:
            return 0.0
        return round(100 * self.booked.get(room, {}).get(day, 0) / available, 1)

    def total(self, room: str) -> int:
        return sum(self.booked.get(room, {}).values())

    def render(self) -> str:
        days = list(date_range(self.first, self.last))
        headers = ["room"] + [format_date(d)[5:] for d in days] + ["total"]
        rows = []
        for room in sorted(self.booked):
            rows.append(
                [room]
                + [f"{self.percent(room, d):.0f}%" for d in days]
                + [f"{self.total(room)} min"]
            )
        return formatting.table(headers, rows) + "\n"


def utilisation(store: Store, clinic_id: str, first: date, last: date) -> Utilisation:
    if last < first:
        raise ValidationError("the report ends before it starts")
    if (last - first).days > 92:
        raise ValidationError("utilisation covers at most 93 days")
    repo = Repository(store)
    clinic = repo.clinic(clinic_id)
    report = Utilisation(clinic_id, first, last)
    rooms = repo.rooms_of(clinic_id)
    for room in rooms:
        report.booked[room.id] = {}
    for day in date_range(first, last):
        report.open_minutes[day] = 0 if clinic.is_closed(day) else clinic.hours.open_minutes(day)
        start = local_midnight(day, clinic.tz)
        end = local_midnight(day + timedelta(days=1), clinic.tz)
        for appt in repo.appointments_between(clinic_id, start, end):
            if appt.status not in COUNTED:
                continue
            per_room = report.booked.setdefault(appt.room, {})
            per_room[day] = per_room.get(day, 0) + appt.minutes
    return report
