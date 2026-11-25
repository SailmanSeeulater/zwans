"""Shared bits for the CLI commands: the context a handler gets, argument parsing for
money and quantities, and small printing helpers."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from shopdesk.clock import Clock
from shopdesk.errors import InvalidInput
from shopdesk.money import format_money, parse_money
from shopdesk.shop import Shop

Handler = Callable[["Context", argparse.Namespace], int]


@dataclass
class Context:
    shop: Shop
    path: Path
    out: TextIO
    err: TextIO
    clock: Clock

    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    def money(self, cents: int) -> str:
        return format_money(cents, self.shop.settings.currency)


def command(
    commands: Any, name: str, handler: Handler, *, saves: bool = False, help: str | None = None
) -> argparse.ArgumentParser:
    parser = commands.add_parser(name, help=help, description=help)
    parser.set_defaults(handler=handler, saves=saves)
    return parser


def group(commands: Any, name: str, help: str) -> Any:
    parser = commands.add_parser(name, help=help, description=help)
    return parser.add_subparsers(dest=f"{name}_command", required=True, metavar="ACTION")


def money_arg(text: str) -> int:
    try:
        return parse_money(text)
    except InvalidInput as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def key_values(pairs: list[str] | None) -> dict[str, str]:
    """["size=M", "colour=red"] -> {"size": "M", "colour": "red"}"""
    result: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise InvalidInput(f"Expected NAME=VALUE, got {pair!r}.")
        result[key.strip()] = value.strip()
    return result
