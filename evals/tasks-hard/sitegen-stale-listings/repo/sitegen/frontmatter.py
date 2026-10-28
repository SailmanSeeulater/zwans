"""Front matter: the `key: value` block between two `---` lines at the top of a file."""

import re
from datetime import date, datetime


class FrontMatterError(Exception):
    pass


_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$")


def split(text: str) -> tuple[str, str]:
    """Split a file into its front matter block and its body."""
    text = text.lstrip("﻿")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise FrontMatterError("front matter starts with --- but never ends")


def parse_value(raw: str) -> object:
    raw = raw.strip()
    if raw == "":
        return ""
    if raw[0] == raw[-1] and raw[0] in "\"'" and len(raw) >= 2:
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [parse_value(item) for item in _split_list(inner)]
    lowered = raw.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if _DATE.match(raw):
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise FrontMatterError(f"not a date: {raw}") from exc
    if _DATETIME.match(raw):
        try:
            return datetime.fromisoformat(raw.replace(" ", "T"))
        except ValueError as exc:
            raise FrontMatterError(f"not a date and time: {raw}") from exc
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def _split_list(inner: str) -> list[str]:
    # Split on commas that are not inside quotes.
    items: list[str] = []
    current: list[str] = []
    quote = ""
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [item for item in (i.strip() for i in items) if item]


def parse(text: str) -> tuple[dict[str, object], str]:
    """Return (metadata, body) for a content file."""
    block, body = split(text)
    meta: dict[str, object] = {}
    for number, line in enumerate(block.splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _KEY.match(line)
        if not match:
            raise FrontMatterError(f"line {number}: expected 'key: value', got {line.strip()!r}")
        key, raw = match.groups()
        if key in meta:
            raise FrontMatterError(f"line {number}: {key} is given twice")
        meta[key] = parse_value(raw)
    return meta, body
