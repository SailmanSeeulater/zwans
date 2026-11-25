"""logq on the command line: print the lines of log files that match a pattern.

    python -m logq PATTERN [FILE ...] [-o] [-c] [--max-steps N]
"""

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

from logq.meter import Meter, StepLimitExceeded
from logq.pattern import compile
from logq.syntax import PatternError


def read_lines(name: str) -> Iterator[str]:
    text = sys.stdin.read() if name == "-" else Path(name).read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        yield line.removesuffix("\r")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="logq", description="Search log files.")
    parser.add_argument("pattern")
    parser.add_argument("files", nargs="*", default=["-"])
    parser.add_argument("-o", "--only-matching", action="store_true",
                        help="print only the matched part of each line")
    parser.add_argument("-c", "--count", action="store_true",
                        help="print only how many lines matched")
    parser.add_argument("--max-steps", type=int, default=None, metavar="N",
                        help="give up on a line after N steps (see the README)")
    args = parser.parse_args(argv)

    try:
        pattern = compile(args.pattern)
    except PatternError as error:
        print(f"logq: {error}", file=sys.stderr)
        return 2

    matched = 0
    show_names = len(args.files) > 1
    for name in args.files:
        for number, line in enumerate(read_lines(name), 1):
            meter = Meter(args.max_steps)
            try:
                span = pattern.search(line, meter)
            except StepLimitExceeded:
                print(f"logq: {name}:{number}: gave up after {args.max_steps} steps",
                      file=sys.stderr)
                continue
            if span is None:
                continue
            matched += 1
            if args.count:
                continue
            shown = line[span[0] : span[1]] if args.only_matching else line
            print(f"{name}:{number}:{shown}" if show_names else shown)
    if args.count:
        print(matched)
    return 0 if matched else 1
