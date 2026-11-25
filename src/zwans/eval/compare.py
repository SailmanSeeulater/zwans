"""Compare two eval runs, with confidence intervals so noise isn't mistaken for a change.

The interval comes from a paired bootstrap over tasks: take each task's difference between
the runs (its mean in B minus its mean in A), then resample those differences with
replacement. Each task's difference already carries its attempt-to-attempt noise, so
resampling attempts as well would count that noise twice and hide real changes. In a
simulation of 25 tasks x 3 repeats, this flags about 5% of same-config pairs as different
(as a 95% interval should) and catches a 15-point drop about 60% of the time.
"""

import dataclasses
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import NormalDist

from zwans.eval.runner import NOT_COUNTED, AttemptResult, Report, cache_hit_rate

RESAMPLES = 5_000
CONFIDENCE = 0.95
MIN_TASKS = 5  # below this, resampling tasks says nothing, so nothing is called significant

type Metric = Callable[[AttemptResult], float]

METRICS: dict[str, Metric] = {
    "pass rate": lambda a: 1.0 if a.status == "passed" else 0.0,
    "dollars": lambda a: a.dollars,
    "model calls": lambda a: float(a.model_calls),
    "tool calls": lambda a: float(a.tool_calls),
    "tool errors": lambda a: float(a.tool_errors),
    "seconds": lambda a: a.seconds,
    "compactions": lambda a: float(a.compactions),
    "cache hit rate": lambda a: cache_hit_rate([a]),
}


@dataclass(frozen=True)
class Difference:
    metric: str
    a: float  # mean over tasks, each task weighted equally
    b: float
    low: float  # the confidence interval for b - a
    high: float
    tasks: int  # how many tasks the interval is based on

    @property
    def delta(self) -> float:
        return self.b - self.a

    @property
    def significant(self) -> bool:
        """The interval leaves out zero, so the runs most likely differ."""
        return self.tasks >= MIN_TASKS and (self.low > 0 or self.high < 0)


@dataclass(frozen=True)
class Comparison:
    tasks: list[str]  # compared: in both runs, with at least one counted attempt in each
    only_in_a: list[str]
    only_in_b: list[str]
    differences: list[Difference]
    task_pass_rates: dict[str, tuple[float, float]]  # task -> (a, b)


def compare(a: Report, b: Report, seed: int = 0) -> Comparison:
    by_task_a = _counted_by_task(a.attempts)
    by_task_b = _counted_by_task(b.attempts)
    tasks = sorted(by_task_a.keys() & by_task_b.keys())
    rng = random.Random(seed)  # the same reports always give the same intervals
    differences = [
        _difference(name, metric, tasks, by_task_a, by_task_b, rng)
        for name, metric in METRICS.items()
    ]
    pass_rate = METRICS["pass rate"]
    return Comparison(
        tasks=tasks,
        only_in_a=sorted(by_task_a.keys() - by_task_b.keys()),
        only_in_b=sorted(by_task_b.keys() - by_task_a.keys()),
        differences=differences,
        task_pass_rates={
            t: (_mean(by_task_a[t], pass_rate), _mean(by_task_b[t], pass_rate)) for t in tasks
        },
    )


def pass_rate_difference(
    a: Sequence[AttemptResult], b: Sequence[AttemptResult], seed: int = 0
) -> Difference:
    """How b's pass rate differs from a's over the tasks both attempted, measured the way
    `compare` does. The attempts may be pooled from several runs."""
    by_task_a, by_task_b = _counted_by_task(a), _counted_by_task(b)
    tasks = sorted(by_task_a.keys() & by_task_b.keys())
    pass_rate = METRICS["pass rate"]
    return _difference("pass rate", pass_rate, tasks, by_task_a, by_task_b, random.Random(seed))


def wilson(passed: int, attempts: int) -> tuple[float, float]:
    """The interval for a pass rate seen in this many attempts (the Wilson score interval).

    It stays wide when every attempt passed or failed, so three out of three doesn't read
    as certain. It treats attempts as independent, which repeats of one task aren't quite,
    so it is for showing a range; `pass_rate_difference` is what tells two rows apart."""
    if attempts == 0:
        return 0.0, 1.0
    z = NormalDist().inv_cdf(1 - (1 - CONFIDENCE) / 2)
    rate = passed / attempts
    scale = 1 + z * z / attempts
    middle = (rate + z * z / (2 * attempts)) / scale
    half = z * math.sqrt(rate * (1 - rate) / attempts + z * z / (4 * attempts * attempts)) / scale
    return max(0.0, middle - half), min(1.0, middle + half)


@dataclass(frozen=True)
class Standing:
    """How one way of running the agent did on the tasks every ranked run attempted. Means
    are over tasks, each task weighted equally, as in `compare`."""

    label: str  # agent, model, effort and config, which runs are pooled by
    reports: int
    attempts: int
    passed: int
    pass_rate: float
    dollars: float  # per attempt
    model_calls: float  # per attempt
    seconds: float  # per attempt
    frontier: bool = False  # no other standing passes as often for less, or more for as little

    @property
    def dollars_per_pass(self) -> float | None:
        """What one passed task costs: what an attempt costs over how often one passes."""
        return self.dollars / self.pass_rate if self.pass_rate else None


@dataclass(frozen=True)
class Ranking:
    tasks: list[str]  # ranked on: attempted, and counted, by every standing
    left_out: dict[str, list[str]]  # label -> its tasks that not every standing attempted
    standings: list[Standing]  # best first: highest pass rate, then cheapest per attempt


def run_label(report: Report) -> str:
    label = f"{report.agent} {report.model} {report.effort}"
    return label if report.config.name == "default" else f"{label}, {report.config.name}"


def rank(reports: Sequence[Report]) -> Ranking:
    """Rank ways of running the agent by pass rate and by cost, over the tasks they share.

    Reports with the same agent, model, effort and config are pooled, so the starter, hard
    and injection runs of one model count as one standing. When every standing passes
    nearly everything, pass rate stops telling them apart and what a pass costs, in dollars
    and model calls, is what's left to compare."""
    pooled: dict[str, list[AttemptResult]] = {}
    counts: dict[str, int] = {}
    for report in reports:
        label = run_label(report)
        pooled.setdefault(label, []).extend(report.attempts)
        counts[label] = counts.get(label, 0) + 1
    by_label = {label: _counted_by_task(attempts) for label, attempts in pooled.items()}
    shared = set.intersection(*(set(t) for t in by_label.values())) if by_label else set()
    tasks = sorted(shared)

    standings = []
    for label, by_task in by_label.items():
        if not tasks:
            standings.append(Standing(label, counts[label], 0, 0, 0.0, 0.0, 0.0, 0.0))
            continue
        attempts = [a for t in tasks for a in by_task[t]]
        standings.append(
            Standing(
                label=label,
                reports=counts[label],
                attempts=len(attempts),
                passed=sum(a.status == "passed" for a in attempts),
                pass_rate=_over_tasks(by_task, tasks, METRICS["pass rate"]),
                dollars=_over_tasks(by_task, tasks, METRICS["dollars"]),
                model_calls=_over_tasks(by_task, tasks, METRICS["model calls"]),
                seconds=_over_tasks(by_task, tasks, METRICS["seconds"]),
            )
        )
    standings = [
        dataclasses.replace(s, frontier=bool(tasks) and not _dominated(s, standings))
        for s in standings
    ]
    standings.sort(key=lambda s: (-s.pass_rate, s.dollars, s.label))
    left_out = {label: sorted(set(t) - shared) for label, t in by_label.items() if set(t) - shared}
    return Ranking(tasks=tasks, left_out=left_out, standings=standings)


def _over_tasks(by_task: dict[str, list[AttemptResult]], tasks: list[str], metric: Metric) -> float:
    return _avg([_mean(by_task[t], metric) for t in tasks])


def _dominated(s: Standing, others: Sequence[Standing]) -> bool:
    """Some other standing passes at least as often for no more, and is better at one."""
    return any(
        o.pass_rate >= s.pass_rate
        and o.dollars <= s.dollars
        and (o.pass_rate > s.pass_rate or o.dollars < s.dollars)
        for o in others
    )


def _counted_by_task(attempts: Sequence[AttemptResult]) -> dict[str, list[AttemptResult]]:
    grouped: dict[str, list[AttemptResult]] = {}
    for attempt in attempts:
        if attempt.status not in NOT_COUNTED:
            grouped.setdefault(attempt.task, []).append(attempt)
    return grouped


def _difference(
    name: str,
    metric: Metric,
    tasks: list[str],
    a: dict[str, list[AttemptResult]],
    b: dict[str, list[AttemptResult]],
    rng: random.Random,
) -> Difference:
    if not tasks:
        return Difference(name, 0.0, 0.0, 0.0, 0.0, tasks=0)
    per_task = [_mean(b[t], metric) - _mean(a[t], metric) for t in tasks]
    mean_a = sum(_mean(a[t], metric) for t in tasks) / len(tasks)
    mean_b = sum(_mean(b[t], metric) for t in tasks) / len(tasks)

    deltas = [_avg(rng.choices(per_task, k=len(per_task))) for _ in range(RESAMPLES)]
    deltas.sort()
    tail = (1 - CONFIDENCE) / 2
    low = deltas[int(tail * (RESAMPLES - 1))]
    high = deltas[int((1 - tail) * (RESAMPLES - 1))]
    return Difference(name, mean_a, mean_b, low, high, tasks=len(tasks))


def _mean(attempts: list[AttemptResult], metric: Metric) -> float:
    return _avg([metric(x) for x in attempts])


def _avg(values: list[float]) -> float:
    return sum(values) / len(values)
