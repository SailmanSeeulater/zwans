from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from cronlite.cli import plan
from cronlite.jobs import JobsError, load_jobs, parse_jobs
from cronlite.scheduler import Scheduler, State

REPO = Path(__file__).resolve().parents[1]


def jobs_from(text_jobs: list[dict[str, object]], zone: str = "Europe/Amsterdam"):
    return parse_jobs({"zone": zone, "job": text_jobs})


def test_the_repos_jobs_file_loads() -> None:
    jobs = load_jobs(REPO / "jobs.toml")
    assert [job.name for job in jobs] == [
        "backup",
        "morning-report",
        "ny-standup-reminder",
        "warm-cache",
    ]
    assert jobs[2].zone.name == "America/New_York"
    assert jobs[0].zone.name == "Europe/Amsterdam"


def test_bad_jobs() -> None:
    with pytest.raises(JobsError, match="no command"):
        jobs_from([{"name": "a", "schedule": "daily 01:00"}])
    with pytest.raises(JobsError, match="two jobs"):
        jobs_from([{"name": "a", "schedule": "daily 01:00", "command": "x"}] * 2)
    with pytest.raises(JobsError, match="unknown zone"):
        jobs_from([{"name": "a", "schedule": "daily 01:00", "command": "x", "zone": "Nowhere"}])


def simulate(
    jobs, start: datetime, minutes: int, state: State | None = None
) -> list[tuple[str, str]]:
    """Tick once a minute; return (job, local due time) for every run."""
    ran: list[tuple[str, str]] = []
    scheduler = Scheduler(
        jobs,
        lambda job, due: ran.append((job.name, job.zone.to_local(due).strftime("%a %d %b %H:%M"))),
        state,
    )
    scheduler.start(start)
    for minute in range(minutes + 1):
        scheduler.tick(start + timedelta(minutes=minute))
    return ran


def test_a_summer_weekend() -> None:
    jobs = jobs_from(
        [
            {"name": "backup", "schedule": "daily 02:30", "command": "x"},
            {"name": "report", "schedule": "weekdays 08:00", "command": "x"},
        ]
    )
    friday_noon = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)

    assert simulate(jobs, friday_noon, 3 * 24 * 60) == [
        ("backup", "Sat 04 Jul 02:30"),
        ("backup", "Sun 05 Jul 02:30"),
        ("backup", "Mon 06 Jul 02:30"),
        ("report", "Mon 06 Jul 08:00"),
    ]


def test_missed_runs_run_once_after_a_restart(tmp_path: Path) -> None:
    jobs = jobs_from([{"name": "hourly", "schedule": "every 1h", "command": "x"}])
    state = State(tmp_path / "state.json")
    start = datetime(2026, 7, 1, 9, 30, tzinfo=UTC)
    scheduler = Scheduler(jobs, lambda job, due: None, state)
    scheduler.start(start)
    assert state.next_due["hourly"] == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    later = datetime(2026, 7, 1, 13, 20, tzinfo=UTC)  # down for three runs
    restarted = Scheduler(jobs, lambda job, due: None, State(tmp_path / "state.json"))
    restarted.start(later)
    runs = restarted.tick(later)

    assert [run.at for run in runs] == [datetime(2026, 7, 1, 10, 0, tzinfo=UTC)]
    assert restarted.state.next_due["hourly"] == datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    assert restarted.tick(later + timedelta(minutes=1)) == []


def test_disabled_jobs_dont_run() -> None:
    jobs = jobs_from([{"name": "off", "schedule": "every 30m", "command": "x", "enabled": False}])
    assert simulate(jobs, datetime(2026, 7, 1, tzinfo=UTC), 120) == []


def test_plan_on_an_ordinary_day() -> None:
    jobs = load_jobs(REPO / "jobs.toml")
    lines = [line for line in plan(jobs, date(2026, 7, 6), 1) if "warm-cache" not in line]
    assert lines == [
        "Mon 06 Jul 02:30 (+02:00)  backup",
        "Mon 06 Jul 08:00 (+02:00)  morning-report",
        "Mon 06 Jul 09:45 (-04:00)  ny-standup-reminder",
    ]
