"""Command line: check a config, or replay a request log through a gateway."""

import argparse
import sys
from pathlib import Path
from typing import TextIO

from tollgate.clock import ManualClock
from tollgate.config import ConfigError, parse_config
from tollgate.gateway import KEY_HEADER, Gateway
from tollgate.http import Request
from tollgate.upstreams import EchoUpstream, Upstream


def parse_log_line(line: str, number: int) -> tuple[float, str, str, str] | None:
    """`<clock reading> <key> <method> <path>`; blank lines and # comments are skipped.
    A key of `-` means the request has no key."""
    text = line.split("#", 1)[0].strip()
    if not text:
        return None
    parts = text.split()
    if len(parts) != 4:
        raise ValueError(f"line {number}: expected 4 fields, got {len(parts)}")
    reading, key, method, path = parts
    try:
        value = float(reading)
    except ValueError:
        raise ValueError(f"line {number}: {reading!r} is not a clock reading") from None
    return value, key, method, path


def replay(config_text: str, log: TextIO, out: TextIO) -> dict[int, int]:
    config = parse_config(config_text)
    upstreams: dict[str, Upstream] = {
        route.upstream: EchoUpstream(route.upstream) for route in config.routes
    }
    clock = ManualClock()
    gateway = Gateway(config, upstreams, clock)
    counts: dict[int, int] = {}
    for number, line in enumerate(log, start=1):
        entry = parse_log_line(line, number)
        if entry is None:
            continue
        reading, key, method, path = entry
        clock.set(reading)
        headers = {} if key == "-" else {KEY_HEADER: key}
        response = gateway.handle(Request(method, path, headers))
        counts[response.status] = counts.get(response.status, 0) + 1
        extra = ""
        if response.status == 429:
            extra = f" retry-after={response.headers['Retry-After']}"
        out.write(f"{reading:g} {key} {method} {path} -> {response.status}{extra}\n")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tollgate")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="check a config file")
    check.add_argument("config", type=Path)
    run = commands.add_parser("replay", help="replay a request log")
    run.add_argument("config", type=Path)
    run.add_argument("log", type=Path)
    args = parser.parse_args(argv)

    try:
        text = args.config.read_text("utf-8")
        if args.command == "check":
            config = parse_config(text)
            print(
                f"ok: {len(config.plans)} plans, {len(config.keys)} keys, "
                f"{len(config.routes)} routes"
            )
            return 0
        with args.log.open(encoding="utf-8") as log:
            counts = replay(text, log, sys.stdout)
    except (OSError, ConfigError, ValueError) as error:
        print(f"tollgate: {error}", file=sys.stderr)
        return 1
    summary = ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))
    print(f"-- {summary or 'no requests'}")
    return 0
