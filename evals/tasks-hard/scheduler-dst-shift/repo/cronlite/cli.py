"""cronlite list | plan | run"""

import argparse
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from cronlite.jobs import Job, JobsError, load_jobs
from cronlite.scheduler import Scheduler, State
from cronlite.schedules import runs_between
from cronlite.tasks import TASKS
from cronlite.timeutil import format_local


def plan(jobs: list[Job], start: date, days: int) -> list[str]:
    """Lines describing every run from local midnight on `start` for `days` days."""
    lines = []
    for job in jobs:
        begin = job.zone.to_utc(datetime.combine(start, datetime.min.time())) - timedelta(seconds=1)
        finish = job.zone.to_utc(
            datetime.combine(start + timedelta(days=days), datetime.min.time())
        )
        for moment in runs_between(job.schedule, job.zone, begin, finish - timedelta(seconds=1)):
            lines.append((moment, f"{format_local(moment, job.zone)}  {job.name}"))
    return [line for _, line in sorted(lines)]


def run_job(job: Job, due: datetime) -> None:
    function = TASKS.get(job.command)
    if function is None:
        print(f"{job.name}: no task called {job.command!r}", file=sys.stderr)
        return
    print(
        f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z running {job.name} (due {format_local(due, job.zone)})"
    )
    try:
        function(job.args)
    except Exception as exc:  # one failing job mustn't stop the others
        print(f"{job.name} failed: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cronlite")
    parser.add_argument("--jobs", default="jobs.toml")
    parser.add_argument("--state", default="cronlite-state.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--from", dest="start", type=date.fromisoformat, default=date.today())
    plan_parser.add_argument("--days", type=int, default=1)
    commands.add_parser("run")
    args = parser.parse_args(argv)

    try:
        jobs = load_jobs(Path(args.jobs))
    except JobsError as exc:
        print(f"cronlite: {exc}", file=sys.stderr)
        return 1

    if args.command == "plan":
        print("\n".join(plan(jobs, args.start, args.days)))
        return 0

    scheduler = Scheduler(jobs, run_job, State(Path(args.state)))
    scheduler.start(datetime.now(UTC))
    if args.command == "list":
        for job, due in scheduler.upcoming():
            print(f"{job.name:20} {job.schedule.describe():18} next {format_local(due, job.zone)}")
        return 0

    try:
        while True:
            scheduler.tick(datetime.now(UTC))
            time.sleep(60 - datetime.now(UTC).second)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
