"""Checks that hold for every command and event, present and future."""

import re
from pathlib import Path

from orderdesk.aggregate import _APPLY
from orderdesk.cli import BUILDERS, build_parser
from orderdesk.commands import COMMANDS
from orderdesk.events import EVENT_TYPES

DOCS = Path(__file__).resolve().parents[1] / "docs" / "commands.md"


def test_every_command_is_documented() -> None:
    sections = re.findall(r"^## (\S+)$", DOCS.read_text("utf-8"), flags=re.MULTILINE)
    assert sorted(sections) == sorted(COMMANDS)


def test_every_command_has_a_permission_in_the_docs() -> None:
    text = DOCS.read_text("utf-8")
    for spec in COMMANDS.values():
        assert f"Permission: `{spec.permission}`" in text, spec.name


def test_every_command_can_be_run_from_the_cli() -> None:
    assert set(BUILDERS) == set(COMMANDS)
    subcommands = build_parser()._subparsers._group_actions[0].choices
    assert set(COMMANDS) <= set(subcommands)


def test_every_event_type_can_be_applied() -> None:
    assert set(EVENT_TYPES.values()) == set(_APPLY)
