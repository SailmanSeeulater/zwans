"""A tiny calculator: evaluates expressions like "2 + 3 * (4 - 1)"."""

import re

TOKEN = re.compile(r"\s*(\d+(?:\.\d+)?|[-+*/()])")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    text = text.rstrip()
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None:
            raise ValueError(f"Unexpected character at {position}: {text[position]!r}")
        tokens.append(match.group(1))
        position = match.end()
    return tokens


def evaluate(text: str) -> float:
    value, rest = _expression(tokenize(text))
    if rest:
        raise ValueError(f"Unexpected {rest[0]!r}")
    return value


def _expression(tokens: list[str]) -> tuple[float, list[str]]:
    value, tokens = _term(tokens)
    while tokens and tokens[0] in ("+", "-"):
        operator, tokens = tokens[0], tokens[1:]
        right, tokens = _expression(tokens)
        value = value + right if operator == "+" else value - right
    return value, tokens


def _term(tokens: list[str]) -> tuple[float, list[str]]:
    value, tokens = _factor(tokens)
    while tokens and tokens[0] in ("*", "/"):
        operator, tokens = tokens[0], tokens[1:]
        right, tokens = _factor(tokens)
        value = value * right if operator == "*" else value / right
    return value, tokens


def _factor(tokens: list[str]) -> tuple[float, list[str]]:
    if not tokens:
        raise ValueError("Expected a number")
    head, rest = tokens[0], tokens[1:]
    if head == "-":
        value, rest = _factor(rest)
        return -value, rest
    if head == "(":
        value, rest = _expression(rest)
        if not rest or rest[0] != ")":
            raise ValueError("Missing )")
        return value, rest[1:]
    return float(head), rest
