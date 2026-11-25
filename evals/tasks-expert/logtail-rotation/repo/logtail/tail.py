"""Following several files at once, and the `python -m logtail` command."""

import argparse
import json
import re
import sys
import time
from typing import Callable, TextIO

from logtail.follower import Follower
from logtail.osfs import OSFS


class Tail:
    """A set of followers polled together; each line comes with the path it came from."""

    def __init__(self, fs, paths: list[str], **options) -> None:
        self.followers = {path: Follower(fs, path, **options) for path in paths}

    def poll(self) -> list[tuple[str, str]]:
        found = []
        for path, follower in self.followers.items():
            found += [(path, line) for line in follower.poll()]
        return found

    def close(self) -> None:
        for follower in self.followers.values():
            follower.close()


class Printer:
    """Formats lines for the terminal: plain, prefixed with their file, or as JSON."""

    def __init__(self, out: TextIO, prefix: bool, as_json: bool = False,
                 pattern: str | None = None) -> None:
        self.out = out
        self.prefix = prefix
        self.as_json = as_json
        self.pattern = re.compile(pattern) if pattern else None
        self.counts: dict[str, int] = {}

    def show(self, path: str, line: str) -> None:
        if self.pattern is not None and not self.pattern.search(line):
            return
        number = self.counts[path] = self.counts.get(path, 0) + 1
        if self.as_json:
            self.out.write(json.dumps({"file": path, "n": number, "line": line}) + "\n")
        elif self.prefix:
            self.out.write(f"{path}: {line}\n")
        else:
            self.out.write(line + "\n")


def run(
    tail: Tail,
    printer: Printer,
    interval: float,
    polls: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    done = 0
    while polls is None or done < polls:
        for path, line in tail.poll():
            printer.show(path, line)
        printer.out.flush()
        done += 1
        if polls is None or done < polls:
            sleep(interval)


def main(argv: list[str] | None = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="logtail", description="Follow log files by name.")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("-n", "--from-end", action="store_true",
                        help="skip what the files already hold")
    parser.add_argument("-s", "--interval", type=float, default=1.0,
                        help="seconds between polls")
    parser.add_argument("--polls", type=int, default=None, help="stop after this many polls")
    parser.add_argument("-g", "--grep", metavar="REGEX", help="only lines that match")
    parser.add_argument("--json", action="store_true", help="one JSON object per line")
    args = parser.parse_args(argv)
    tail = Tail(OSFS(), args.paths, from_end=args.from_end)
    printer = Printer(out, prefix=len(args.paths) > 1, as_json=args.json, pattern=args.grep)
    try:
        run(tail, printer, args.interval, polls=args.polls)
    except KeyboardInterrupt:
        pass
    finally:
        tail.close()
    return 0
