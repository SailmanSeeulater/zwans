"""linediff on the command line.

    python -m linediff OLD NEW [-U N]     print a unified diff (exit 1 if the files differ)
    python -m linediff --apply PATCH FILE print FILE with PATCH applied
"""

import argparse
import sys
from pathlib import Path

from linediff.patch import PatchError, apply
from linediff.unified import unified


def read_lines(path: str) -> list[str]:
    """A file's lines, split on "\\n"; a final newline doesn't make an extra empty line."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def join_lines(lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linediff", description="Line diffs and patches.")
    parser.add_argument("first", help="the old file (or, with --apply, the patch)")
    parser.add_argument("second", help="the new file (or, with --apply, the file to patch)")
    parser.add_argument("-U", "--unified", type=int, default=3, metavar="N",
                        help="lines of context around each change (default 3)")
    parser.add_argument("--apply", action="store_true", help="apply a patch instead")
    args = parser.parse_args(argv)

    if args.apply:
        patch = Path(args.first).read_text(encoding="utf-8")
        try:
            result = apply(patch, read_lines(args.second))
        except PatchError as error:
            print(f"linediff: {error}", file=sys.stderr)
            return 2
        sys.stdout.write(join_lines(result))
        return 0

    if args.unified < 0:
        parser.error("-U can't be negative")
    text = unified(read_lines(args.first), read_lines(args.second), args.unified,
                   args.first, args.second)
    sys.stdout.write(text)
    return 1 if text else 0
