# fairq

A job scheduler for a shared worker pool. Many tenants submit jobs; workers ask for the
next one with `pull()`. fairq decides who goes next: priorities, with waiting jobs slowly
gaining priority so nothing waits forever; a fair share of the workers for every tenant;
and deadlines, after which a job is no longer worth running.

```python
from fairq import ManualClock, Scheduler

clock = ManualClock()            # or any function returning whole seconds
scheduler = Scheduler(clock)
scheduler.submit("report-17", tenant="acme", priority=2, size=3, deadline=600)
scheduler.submit("thumb-9", tenant="globex")
job = scheduler.pull("worker-1")  # a Job, or None when nothing is waiting
```

## Jobs

`submit(job_id, tenant, priority=0, size=1, deadline=None)` adds a job and returns its
`Job`. The job is enqueued at the clock's current time (`job.enqueued_at`).

- `job_id` must be new: submitting an id that was ever submitted before raises
  `ValueError`.
- `priority` is an integer; higher runs sooner.
- `size` is a whole number of work units, at least 1: roughly how much of a worker the
  job takes. Fair share is counted in units, not jobs.
- `deadline` is a time on the clock, or `None` for no deadline.

The clock is any function that returns the time in whole seconds; it never goes back.

A job is `waiting` until it is handed out (`running`), cancelled (`cancelled`) or dropped
(`dropped`). `scheduler.job(job_id)` returns any job ever submitted.

## Which job a pull hands out

`pull(worker)` at time `now` does this:

1. **Deadlines.** Every waiting job whose deadline is earlier than `now` is dropped: it
   will never run, its state becomes `dropped`, and it is appended to the
   `scheduler.dropped` list. Jobs dropped by the same pull are appended in order of
   deadline, then of submission. A job whose deadline is exactly `now` can still run.
   Nothing but a pull drops jobs.
2. If no job is waiting now, `pull` returns `None`.
3. **Fair share: which tenant.** A tenant's *usage* is the total size of its jobs handed
   out in the last 60 seconds: a job handed out at time `t` counts while `now - t < 60`.
   Its *share* is its usage divided by its weight (1 unless set with
   `set_weight(tenant, weight)`, a whole number of at least 1). The pull serves the
   tenant with the lowest share among the tenants that have waiting jobs. When several
   tenants tie for the lowest share, it serves the one whose next job (by rule 4) would
   come first if all their jobs were sorted together by rule 4.
4. **Priority with aging: which job.** Within the tenant, the job with the highest
   *effective priority* goes first. A job's effective priority is its priority plus one
   for every 30 seconds it has waited, counted exactly: after 45 seconds of waiting it
   has gained 1.5. There is no rounding and no cap. Jobs with equal effective priority go
   in the order they were enqueued (earlier `enqueued_at` first), then in the order they
   were submitted.
5. The job becomes `running`, with `job.worker` and `job.started_at` set, and counts
   towards its tenant's usage from now on.

`cancel(job_id)` takes a waiting job out of the queue and returns `True`; for any other
job it returns `False`. `reprioritize(job_id, priority)` sets a waiting job's priority
and returns `True` (`False` if the job isn't waiting); the time it has waited still
counts from when it was submitted. Cancelling, reprioritizing and changing weights take
effect from the very next pull.

`Scheduler(clock, aging_period=30, share_window=60)` lets the 30 seconds of rule 4 and the
60 seconds of rule 3 be changed.

## What a pull costs

Queues get long (hundreds of thousands of jobs), so the scheduler can't look at every
waiting job to make each decision.

Pass `stats=` to the constructor (a `fairq.Stats`, or any object with a `visits`
attribute) to count the work. The scheduler adds one to `stats.visits` for every job
record it handles while submitting, pulling, cancelling or reprioritizing: each job
pushed onto a heap or popped off one is one visit (each a few comparisons, O(log n)), and
so is each job looked at in a loop or search through jobs. Looking at the top of a heap
is free, and so is anything done per tenant (tenants are few) or to the record of past
pulls.

**At any moment, the visits so far are at most 6 times the number of `submit` and
`reprioritize` calls made so far.**

## Replaying workloads

```
python -m fairq WORKLOAD.jsonl
```

replays a recorded workload (see `fairq/replay.py` for the format) and prints what each
pull handed out or dropped.

## Tests

```
python -m pytest -q
```
