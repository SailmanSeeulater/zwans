"""python -m relaydns ZONE NAME TYPE [NAME TYPE ...]"""

import argparse
import asyncio
import sys
from pathlib import Path

from relaydns.clock import MonotonicClock
from relaydns.records import BadName
from relaydns.resolver import Resolver
from relaydns.upstream import FakeUpstream
from relaydns.zone import Zone, ZoneError


async def run(zone: Zone, questions: list[tuple[str, str]]) -> list[str]:
    upstream = FakeUpstream(zone)
    resolver = Resolver(upstream, MonotonicClock())
    answers = await asyncio.gather(*(resolver.resolve(name, rtype) for name, rtype in questions))
    out = []
    for (name, rtype), answer in zip(questions, answers):
        out.append(f";; {name} {rtype}\n{answer.render()}")
    out.append(f";; upstream requests: {upstream.requests}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relaydns")
    parser.add_argument("zone", type=Path)
    parser.add_argument("questions", nargs="+", metavar="NAME TYPE")
    args = parser.parse_args(argv)
    if len(args.questions) % 2:
        parser.error("questions come in pairs: NAME TYPE")
    questions = list(zip(args.questions[::2], args.questions[1::2]))
    try:
        zone = Zone.parse(args.zone.read_text("utf-8"))
        for block in asyncio.run(run(zone, questions)):
            print(block)
            print()
    except (OSError, ZoneError, BadName) as error:
        print(f"relaydns: {error}", file=sys.stderr)
        return 1
    return 0
