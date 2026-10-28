"""Jobs, as listed in jobs.toml.

zone = "Europe/Amsterdam"

[[job]]
name = "backup"
schedule = "daily 02:30"
command = "backup"            # a registered task, see tasks.py

[[job]]
name = "ny-report"
schedule = "weekdays 08:00"
zone = "America/New_York"     # overrides the default zone
command = "report"
args = ["--region", "us"]
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from cronlite.schedules import Schedule, ScheduleError, parse_schedule
from cronlite.zones import UnknownZone, Zone, get_zone


class JobsError(Exception):
    pass


@dataclass(frozen=True)
class Job:
    name: str
    schedule: Schedule
    zone: Zone
    command: str
    args: tuple[str, ...] = field(default=())
    enabled: bool = True


def parse_jobs(data: dict[str, object]) -> list[Job]:
    try:
        default_zone = get_zone(str(data.get("zone", "UTC")))
    except UnknownZone as exc:
        raise JobsError(str(exc)) from None
    entries = data.get("job", [])
    if not isinstance(entries, list):
        raise JobsError("[[job]] entries expected")
    jobs: list[Job] = []
    names: set[str] = set()
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise JobsError(f"job {number} is not a table")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise JobsError(f"job {number} has no name")
        if name in names:
            raise JobsError(f"two jobs are called {name!r}")
        names.add(name)
        try:
            schedule = parse_schedule(str(entry.get("schedule", "")))
            zone = get_zone(str(entry["zone"])) if "zone" in entry else default_zone
        except (ScheduleError, UnknownZone) as exc:
            raise JobsError(f"job {name!r}: {exc}") from None
        command = str(entry.get("command", "")).strip()
        if not command:
            raise JobsError(f"job {name!r} has no command")
        args = entry.get("args", [])
        if not isinstance(args, list):
            raise JobsError(f"job {name!r}: args must be a list")
        jobs.append(
            Job(
                name,
                schedule,
                zone,
                command,
                tuple(str(a) for a in args),
                bool(entry.get("enabled", True)),
            )
        )
    return jobs


def load_jobs(path: Path) -> list[Job]:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise JobsError(f"{path} not found") from None
    except tomllib.TOMLDecodeError as exc:
        raise JobsError(f"{path}: {exc}") from None
    return parse_jobs(data)
