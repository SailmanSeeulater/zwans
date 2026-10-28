"""Compare two eval runs, with confidence intervals so noise isn't mistaken for a change.

The interval comes from a paired bootstrap over tasks: take each task's difference between
the runs (its mean in B minus its mean in A), then resample those differences with
replacement. Each task's difference already carries its attempt-to-attempt noise, so
resampling attempts as well would count that noise twice and hide real changes. In a
simulation of 25 tasks x 3 repeats, this flags about 5% of same-config pairs as different
(as a 95% interval should) and catches a 15-point drop about 60% of the time.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from zwans.eval.runner import AttemptResult, Report

RESAMPLES = 5_000
CONFIDENCE = 0.95
MIN_TASKS = 5  # below this, resampling tasks says nothing, so nothing is called significant

type Metric = Callable[[AttemptResult], float]

METRICS: dict[str, Metric] = {
    "pass rate": lambda a: 1.0 if a.status == "passed" else 0.0,
    "dollars": lambda a: a.dollars,
    "model calls": lambda a: float(a.model_calls),
    "tool calls": lambda a: float(a.tool_calls),
    "seconds": lambda a: a.seconds,
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


def _counted_by_task(attempts: Sequence[AttemptResult]) -> dict[str, list[AttemptResult]]:
    grouped: dict[str, list[AttemptResult]] = {}
    for attempt in attempts:
        if attempt.status != "stopped":
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
