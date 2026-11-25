"""Splits SQL text into tokens."""

from dataclasses import dataclass

from minisql.errors import SQLError

KEYWORDS = frozenset(
    """
    SELECT DISTINCT ALL FROM WHERE GROUP BY HAVING ORDER ASC DESC NULLS FIRST LAST LIMIT
    OFFSET AS JOIN INNER LEFT OUTER CROSS ON AND OR NOT IS NULL IN BETWEEN CASE WHEN THEN
    ELSE END CREATE TABLE DROP IF EXISTS INSERT INTO VALUES DELETE UPDATE SET EXPLAIN
    """.split()
)

# Longest first, so "<=" wins over "<".
OPERATORS = (
    "<=", ">=", "<>", "!=", "==", "||",
    "(", ")", ",", ".", ";", "*", "+", "-", "/", "=", "<", ">",
)


@dataclass(frozen=True)
class Token:
    kind: str  # "keyword", "name", "integer", "string", "op" or "end"
    value: object
    position: int

    def is_keyword(self, *words: str) -> bool:
        return self.kind == "keyword" and self.value in words

    def is_op(self, *ops: str) -> bool:
        return self.kind == "op" and self.value in ops

    def describe(self) -> str:
        if self.kind == "end":
            return "end of input"
        if self.kind == "string":
            return f"'{self.value}'"
        return str(self.value)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if text.startswith("--", i):
            end = text.find("\n", i)
            i = length if end == -1 else end + 1
            continue
        if char.isdigit():
            start = i
            while i < length and text[i].isdigit():
                i += 1
            if i < length and (text[i].isalpha() or text[i] in "._"):
                raise SQLError(f"bad number at position {start}")
            tokens.append(Token("integer", int(text[start:i]), start))
            continue
        if char.isalpha() or char == "_":
            start = i
            while i < length and (text[i].isalnum() or text[i] == "_"):
                i += 1
            word = text[start:i]
            if word.upper() in KEYWORDS:
                tokens.append(Token("keyword", word.upper(), start))
            else:
                tokens.append(Token("name", word.lower(), start))
            continue
        if char == "'":
            start = i
            value, i = _quoted(text, i, "'")
            tokens.append(Token("string", value, start))
            continue
        if char == '"':
            start = i
            value, i = _quoted(text, i, '"')
            if not value:
                raise SQLError(f"empty name at position {start}")
            tokens.append(Token("name", value.lower(), start))
            continue
        for op in OPERATORS:
            if text.startswith(op, i):
                tokens.append(Token("op", op, i))
                i += len(op)
                break
        else:
            raise SQLError(f"unexpected character {char!r} at position {i}")
    tokens.append(Token("end", None, length))
    return tokens


def _quoted(text: str, start: int, quote: str) -> tuple[str, int]:
    """The text between quotes starting at `start` (a doubled quote stands for one)."""
    parts: list[str] = []
    i = start + 1
    while True:
        end = text.find(quote, i)
        if end == -1:
            raise SQLError(f"unterminated quote at position {start}")
        parts.append(text[i:end])
        if text.startswith(quote * 2, end):
            parts.append(quote)
            i = end + 2
            continue
        return "".join(parts), end + 1
