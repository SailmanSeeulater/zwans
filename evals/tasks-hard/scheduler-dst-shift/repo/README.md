# cronlite

The office job scheduler: nightly backups, morning reports, cache warmers. Jobs
are listed in `jobs.toml`; `cronlite run` checks every minute which jobs are due
and runs them.

## Schedules

| schedule              | meaning                                                   |
|-----------------------|-----------------------------------------------------------|
| `daily 02:30`         | every day at 02:30 local time                             |
| `weekdays 08:00`      | Monday to Friday at 08:00 local time                      |
| `mon,thu 07:15`       | on those days of the week at 07:15 local time             |
| `every 30m` / `every 2h` | every 30 minutes / 2 hours of elapsed time             |

"Local time" is the wall-clock time of the job's `zone` (default: the
`zone` at the top of `jobs.toml`). A job set for 08:00 runs when the office
clock says 08:00, in summer and in winter.

Daylight saving time:

- When the clocks go back, the hour before the change happens twice. A job
  whose time falls in that hour runs **once**, at the first of the two
  moments (the one still on summer time).
- When the clocks go forward, an hour is skipped. A job whose time falls in
  the skipped hour runs at the first moment after the gap, e.g. a 02:30 job
  in Amsterdam runs at 03:00 on that day. On other days it runs at 02:30 as
  usual.
- `every` schedules count real elapsed time from midnight UTC and ignore the
  clocks entirely: an `every 1h` job runs 25 times on the day the clocks go
  back and 23 times on the day they go forward.

If the scheduler was down and a job missed runs, it runs once when the
scheduler comes back, and then carries on with its next run after that.

## Zones

To avoid depending on the system's time zone database (our Windows boxes don't
have one), cronlite knows a handful of zones itself (`cronlite/zones.py`), each
a standard UTC offset plus a daylight-saving rule:

- `eu`: summer time from 01:00 UTC on the last Sunday of March to 01:00 UTC
  on the last Sunday of October;
- `us`: from 02:00 local time on the second Sunday of March to 02:00 local
  time on the first Sunday of November;
- `none`.

## Commands

```
cronlite list                                # jobs and their next run
cronlite plan --from 2026-10-24 --days 3     # when jobs would run, local times
cronlite run                                 # the scheduler loop
```

## Development

```
python -m pytest
```
