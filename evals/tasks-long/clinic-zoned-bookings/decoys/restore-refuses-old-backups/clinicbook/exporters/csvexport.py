"""CSV export of appointments, for the finance team's spreadsheets."""

from __future__ import annotations

import csv
import io
from datetime import date

from ..repository import Repository
from ..storage import Store
from ..timeutil import format_instant

COLUMNS = [
    "id",
    "clinic",
    "clinician",
    "room",
    "patient",
    "patient_name",
    "date",
    "start",
    "end",
    "minutes",
    "kind",
    "status",
    "series",
    "utc_start",
    "utc_end",
]


def export_csv(
    store: Store,
    *,
    clinic: str | None = None,
    first: date | None = None,
    last: date | None = None,
    status: str | None = None,
) -> str:
    repo = Repository(store)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for appt in repo.appointments(clinic=clinic, status=status):
        day = appt.start.date()
        if (first is not None and day < first) or (last is not None and day > last):
            continue
        writer.writerow(
            {
                "id": appt.id,
                "clinic": appt.clinic,
                "clinician": appt.clinician,
                "room": appt.room,
                "patient": appt.patient,
                "patient_name": repo.patient(appt.patient).name,
                "date": day.isoformat(),
                "start": appt.start.strftime("%H:%M"),
                "end": appt.end.strftime("%H:%M"),
                "minutes": appt.minutes,
                "kind": appt.kind,
                "status": appt.status,
                "series": appt.series or "",
                "utc_start": format_instant(appt.start),
                "utc_end": format_instant(appt.end),
            }
        )
    return out.getvalue()
