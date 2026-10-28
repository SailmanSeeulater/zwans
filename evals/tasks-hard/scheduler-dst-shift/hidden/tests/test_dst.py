from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from cronlite.cli import plan
from cronlite.jobs import load_jobs, parse_jobs
from cronlite.scheduler import Scheduler
from cronlite.schedules import parse_schedule, runs_between
from cronlite.zones import get_zone

REPO = Path(__file__).resolve().parents[1]
AMSTERDAM = get_zone("Europe/Amsterdam")
LONDON = get_zone("Europe/London")
NEW_YORK = get_zone("America/New_York")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def local_runs(text: str, zone, first_day: date, days: int) -> list[str]:
    """Runs of a schedule from local midnight on first_day, for `days` local days."""
    start = zone.to_utc(datetime.combine(first_day, datetime.min.time())) - timedelta(seconds=1)
    end = zone.to_utc(
        datetime.combine(first_day + timedelta(days=days), datetime.min.time())
    ) - timedelta(seconds=1)
    return [
        zone.aware(moment).strftime("%a %d %H:%M %z")
        for moment in runs_between(parse_schedule(text), zone, start, end)
    ]


# --- converting wall-clock times ----------------------------------------------------


@pytest.mark.parametrize(
    ("zone", "local", "expected"),
    [
        (AMSTERDAM, datetime(2026, 10, 25, 2, 0), utc(2026, 10, 25, 0, 0)),
        (AMSTERDAM, datetime(2026, 10, 25, 2, 30), utc(2026, 10, 25, 0, 30)),
        (AMSTERDAM, datetime(2026, 10, 25, 2, 59), utc(2026, 10, 25, 0, 59)),
        (LONDON, datetime(2026, 10, 25, 1, 30), utc(2026, 10, 25, 0, 30)),
        (NEW_YORK, datetime(2026, 11, 1, 1, 30), utc(2026, 11, 1, 5, 30)),
    ],
)
def test_a_time_that_happens_twice_means_the_first_time(zone, local, expected) -> None:
    assert zone.to_utc(local) == expected


@pytest.mark.parametrize(
    ("zone", "local", "expected"),
    [
        (AMSTERDAM, datetime(2026, 3, 29, 2, 0), utc(2026, 3, 29, 1, 0)),
        (AMSTERDAM, datetime(2026, 3, 29, 2, 30), utc(2026, 3, 29, 1, 0)),
        (AMSTERDAM, datetime(2026, 3, 29, 2, 59), utc(2026, 3, 29, 1, 0)),
        (LONDON, datetime(2026, 3, 29, 1, 30), utc(2026, 3, 29, 1, 0)),
        (NEW_YORK, datetime(2026, 3, 8, 2, 30), utc(2026, 3, 8, 7, 0)),
    ],
)
def test_a_skipped_time_means_the_end_of_the_gap(zone, local, expected) -> None:
    assert zone.to_utc(local) == expected


@pytest.mark.parametrize(
    ("zone", "day"),
    [
        (AMSTERDAM, date(2026, 10, 25)),
        (AMSTERDAM, date(2026, 3, 29)),
        (LONDON, date(2026, 10, 25)),
        (NEW_YORK, date(2026, 11, 1)),
        (NEW_YORK, date(2026, 3, 8)),
        (get_zone("Asia/Tokyo"), date(2026, 3, 29)),
    ],
)
def test_wall_clock_round_trips_around_a_change(zone, day) -> None:
    moment = utc(day.year, day.month, day.day) - timedelta(hours=12)
    end = moment + timedelta(hours=36)
    while moment < end:
        local = zone.to_local(moment)
        back = zone.to_utc(local)
        # The only instants that don't come back are second occurrences of a repeated time.
        assert back == moment or (
            back == moment - timedelta(hours=1) and zone.to_local(back) == local
        ), moment
        moment += timedelta(minutes=5)


# --- schedules around the changes ---------------------------------------------------


def test_daily_backup_when_the_clocks_go_back_in_amsterdam() -> None:
    assert local_runs("daily 02:30", AMSTERDAM, date(2026, 10, 23), 5) == [
        "Fri 23 02:30 +0200",
        "Sat 24 02:30 +0200",
        "Sun 25 02:30 +0200",
        "Mon 26 02:30 +0100",
        "Tue 27 02:30 +0100",
    ]


def test_weekday_report_when_the_clocks_go_back_in_amsterdam() -> None:
    assert local_runs("weekdays 08:00", AMSTERDAM, date(2026, 10, 22), 6) == [
        "Thu 22 08:00 +0200",
        "Fri 23 08:00 +0200",
        "Mon 26 08:00 +0100",
        "Tue 27 08:00 +0100",
    ]


@pytest.mark.parametrize("at", ["00:15", "01:30", "03:00", "07:00", "23:45"])
def test_other_times_when_the_clocks_go_back(at: str) -> None:
    runs = local_runs(f"daily {at}", AMSTERDAM, date(2026, 10, 24), 4)
    assert [run[4:9] for run in runs] == [
        "24 " + at[:2],
        "25 " + at[:2],
        "26 " + at[:2],
        "27 " + at[:2],
    ]
    assert all(run[10:12] == at[3:] for run in runs)


def test_daily_backup_when_the_clocks_go_forward_in_amsterdam() -> None:
    assert local_runs("daily 02:30", AMSTERDAM, date(2026, 3, 27), 5) == [
        "Fri 27 02:30 +0100",
        "Sat 28 02:30 +0100",
        "Sun 29 03:00 +0200",
        "Mon 30 02:30 +0200",
        "Tue 31 02:30 +0200",
    ]


def test_weekday_report_when_the_clocks_go_forward_in_amsterdam() -> None:
    assert local_runs("weekdays 08:00", AMSTERDAM, date(2026, 3, 26), 6) == [
        "Thu 26 08:00 +0100",
        "Fri 27 08:00 +0100",
        "Mon 30 08:00 +0200",
        "Tue 31 08:00 +0200",
    ]


def test_new_york_changes() -> None:
    assert local_runs("daily 01:30", NEW_YORK, date(2026, 10, 31), 3) == [
        "Sat 31 01:30 -0400",
        "Sun 01 01:30 -0400",
        "Mon 02 01:30 -0500",
    ]
    assert local_runs("daily 03:00", NEW_YORK, date(2026, 10, 31), 3) == [
        "Sat 31 03:00 -0400",
        "Sun 01 03:00 -0500",
        "Mon 02 03:00 -0500",
    ]
    assert local_runs("daily 02:30", NEW_YORK, date(2026, 3, 7), 3) == [
        "Sat 07 02:30 -0500",
        "Sun 08 03:00 -0400",
        "Mon 09 02:30 -0400",
    ]
    assert local_runs("weekdays 09:45", NEW_YORK, date(2026, 3, 6), 4) == [
        "Fri 06 09:45 -0500",
        "Mon 09 09:45 -0400",
    ]


def test_a_sunday_job_in_the_repeated_hour_runs_once() -> None:
    assert local_runs("sun 02:15", AMSTERDAM, date(2026, 10, 18), 15) == [
        "Sun 18 02:15 +0200",
        "Sun 25 02:15 +0200",
        "Sun 01 02:15 +0100",
    ]
    assert local_runs("sun 02:15", AMSTERDAM, date(2026, 3, 22), 15) == [
        "Sun 22 02:15 +0100",
        "Sun 29 03:00 +0200",
        "Sun 05 02:15 +0200",
    ]


def test_every_counts_real_hours() -> None:
    assert len(local_runs("every 1h", AMSTERDAM, date(2026, 10, 25), 1)) == 25
    assert len(local_runs("every 1h", AMSTERDAM, date(2026, 3, 29), 1)) == 23
    assert len(local_runs("every 30m", NEW_YORK, date(2026, 11, 1), 1)) == 50
    assert len(local_runs("every 1h", AMSTERDAM, date(2026, 10, 26), 1)) == 24


# --- the scheduler over the weekends ------------------------------------------------


def simulate(start: datetime, hours: int) -> list[tuple[str, str]]:
    jobs = [job for job in load_jobs(REPO / "jobs.toml") if job.name != "warm-cache"]
    ran: list[tuple[str, str]] = []
    scheduler = Scheduler(
        jobs,
        lambda job, due: ran.append((job.name, job.zone.aware(due).strftime("%a %d %H:%M %z"))),
    )
    scheduler.start(start)
    for minute in range(hours * 60 + 1):
        scheduler.tick(start + timedelta(minutes=minute))
    return ran


def test_the_scheduler_over_the_october_weekend() -> None:
    assert simulate(utc(2026, 10, 23, 12, 0), 4 * 24) == [
        ("ny-standup-reminder", "Fri 23 09:45 -0400"),
        ("backup", "Sat 24 02:30 +0200"),
        ("backup", "Sun 25 02:30 +0200"),
        ("backup", "Mon 26 02:30 +0100"),
        ("morning-report", "Mon 26 08:00 +0100"),
        ("ny-standup-reminder", "Mon 26 09:45 -0400"),
        ("backup", "Tue 27 02:30 +0100"),
        ("morning-report", "Tue 27 08:00 +0100"),
    ]


def test_the_scheduler_over_the_march_weekend() -> None:
    assert simulate(utc(2026, 3, 27, 12, 0), 4 * 24) == [
        ("ny-standup-reminder", "Fri 27 09:45 -0400"),
        ("backup", "Sat 28 02:30 +0100"),
        ("backup", "Sun 29 03:00 +0200"),
        ("backup", "Mon 30 02:30 +0200"),
        ("morning-report", "Mon 30 08:00 +0200"),
        ("ny-standup-reminder", "Mon 30 09:45 -0400"),
        ("backup", "Tue 31 02:30 +0200"),
        ("morning-report", "Tue 31 08:00 +0200"),
    ]


def test_plan_for_the_week_the_clocks_went_back() -> None:
    jobs = parse_jobs(
        {
            "zone": "Europe/Amsterdam",
            "job": [
                {"name": "backup", "schedule": "daily 02:30", "command": "x"},
                {"name": "report", "schedule": "weekdays 08:00", "command": "x"},
            ],
        }
    )
    assert plan(jobs, date(2026, 10, 24), 3) == [
        "Sat 24 Oct 02:30 (+02:00)  backup",
        "Sun 25 Oct 02:30 (+02:00)  backup",
        "Mon 26 Oct 02:30 (+01:00)  backup",
        "Mon 26 Oct 08:00 (+01:00)  report",
    ]
