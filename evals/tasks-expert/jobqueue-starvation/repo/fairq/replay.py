"""Replaying a recorded workload through the scheduler, for debugging and capacity tests.

    python -m fairq WORKLOAD.jsonl

Each line of the workload is a JSON object with the time it happened ("at", in seconds,
never going back) and an "op":

    {"at": 0, "op": "submit", "id": "j1", "tenant": "acme", "priority": 2, "size": 1,
     "deadline": 90}
    {"at": 4, "op": "pull", "worker": "w1"}
    {"at": 5, "op": "cancel", "id": "j1"}
    {"at": 6, "op": "reprioritize", "id": "j2", "priority": 5}
    {"at": 7, "op": "weight", "tenant": "acme", "weight": 3}

The output has one line per job handed out, dropped or not found, prefixed with the time.
"""

import json
import sys
from collections.abc import Iterable

from fairq.jobs import ManualClock
from fairq.scheduler import Scheduler


def replay(lines: Iterable[str]) -> list[str]:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    out: list[str] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        event = json.loads(line)
        clock.set(event["at"])
        at, op = event["at"], event["op"]
        if op == "submit":
            scheduler.submit(event["id"], event["tenant"], event.get("priority", 0),
                             event.get("size", 1), event.get("deadline"))
        elif op == "pull":
            seen = len(scheduler.dropped)
            job = scheduler.pull(event.get("worker", "worker"))
            out.extend(f"{at} dropped {dropped.id}" for dropped in scheduler.dropped[seen:])
            worker = event.get("worker", "worker")
            out.append(f"{at} {worker} idle" if job is None else
                       f"{at} {worker} <- {job.id} ({job.tenant})")
        elif op == "cancel":
            if not scheduler.cancel(event["id"]):
                out.append(f"{at} cancel: {event['id']} isn't waiting")
        elif op == "reprioritize":
            if not scheduler.reprioritize(event["id"], event["priority"]):
                out.append(f"{at} reprioritize: {event['id']} isn't waiting")
        elif op == "weight":
            scheduler.set_weight(event["tenant"], event["weight"])
        else:
            raise ValueError(f"line {number}: unknown op {op!r}")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m fairq WORKLOAD.jsonl", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as workload:
        for line in replay(workload):
            print(line)
    return 0
