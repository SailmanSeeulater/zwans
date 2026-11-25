"""Reading a pattern into a tree. The pattern language is described in the README."""

from dataclasses import dataclass

MAX_COUNT = 1000
SPECIAL = set(".^$*+?()[]{}|\\")
ESCAPABLE = SPECIAL | {"-", "/"}
WORD = (("a", "z"), ("A", "Z"), ("0", "9"), ("_", "_"))
DIGIT = (("0", "9"),)


class PatternError(ValueError):
    """The pattern isn't in the language the README describes."""

    def __init__(self, message: str, pattern: str, position: int) -> None:
        super().__init__(f"{message} at position {position} in {pattern!r}")
        self.position = position


@dataclass(frozen=True)
class Char:
    """One character of text: any character in `ranges`, or with `negated`, any not in them."""

    ranges: tuple[tuple[str, str], ...]
    negated: bool = False

    def test(self, ch: str) -> bool:
        inside = any(low <= ch <= high for low, high in self.ranges)
        return inside != self.negated


@dataclass(frozen=True)
class Seq:
    items: tuple["Node", ...]


@dataclass(frozen=True)
class Alt:
    options: tuple["Node", ...]


@dataclass(frozen=True)
class Repeat:
    item: "Node"
    low: int
    high: int | None  # None: no upper limit


@dataclass(frozen=True)
class Start:
    pass


@dataclass(frozen=True)
class End:
    pass


Node = Char | Seq | Alt | Repeat | Start | End

ANY = Char((("\n", "\n"),), negated=True)


def nullable(node: Node) -> bool:
    """Whether the node can match the empty string."""
    match node:
        case Char():
            return False
        case Start() | End():
            return True
        case Seq(items):
            return all(nullable(item) for item in items)
        case Alt(options):
            return any(nullable(option) for option in options)
        case Repeat(item, low, _):
            return low == 0 or nullable(item)
    raise TypeError(node)


def size(node: Node) -> int:
    """The pattern's size as the README defines it: its character items, counting each
    copy a repeat makes ({m,n}: n copies, {m,}: m + 1 copies)."""
    match node:
        case Char():
            return 1
        case Start() | End():
            return 0
        case Seq(items):
            return sum(size(item) for item in items)
        case Alt(options):
            return sum(size(option) for option in options)
        case Repeat(item, low, high):
            return size(item) * (high if high is not None else low + 1)
    raise TypeError(node)


def parse(pattern: str) -> Node:
    parser = _Parser(pattern)
    node = parser.alternation()
    if parser.pos < len(pattern):
        raise parser.error("unmatched )" if parser.peek() == ")" else "unexpected character")
    return node


class _Parser:
    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.pos = 0

    def error(self, message: str, position: int | None = None) -> PatternError:
        return PatternError(message, self.pattern, self.pos if position is None else position)

    def peek(self) -> str | None:
        return self.pattern[self.pos] if self.pos < len(self.pattern) else None

    def take(self) -> str:
        if self.pos >= len(self.pattern):
            raise self.error("the pattern ends too soon")
        ch = self.pattern[self.pos]
        self.pos += 1
        return ch

    def alternation(self) -> Node:
        options = [self.sequence()]
        while self.peek() == "|":
            self.pos += 1
            options.append(self.sequence())
        return options[0] if len(options) == 1 else Alt(tuple(options))

    def sequence(self) -> Node:
        items: list[Node] = []
        while self.peek() is not None and self.peek() not in "|)":
            start = self.pos
            item = self.atom()
            if self.peek() is not None and self.peek() in "*+?{":
                counts = self.quantifier()
                if nullable(item):
                    raise self.error("nothing to repeat: it can match the empty string", start)
                item = Repeat(item, *counts)
                if self.peek() is not None and self.peek() in "*+?{":
                    raise self.error("a quantifier can't follow another one")
            items.append(item)
        return items[0] if len(items) == 1 else Seq(tuple(items))

    def quantifier(self) -> tuple[int, int | None]:
        ch = self.take()
        if ch == "*":
            return 0, None
        if ch == "+":
            return 1, None
        if ch == "?":
            return 0, 1
        start = self.pos - 1
        low = self.number()
        high: int | None = low
        if self.peek() == ",":
            self.pos += 1
            high = None if self.peek() == "}" else self.number()
        if self.take() != "}":
            raise self.error("expected } to close the count", start)
        if high is not None and high < low:
            raise self.error("the count's minimum is above its maximum", start)
        if max(low, high or 0) > MAX_COUNT:
            raise self.error(f"counts go up to {MAX_COUNT}", start)
        return low, high

    def number(self) -> int:
        start = self.pos
        while self.peek() is not None and self.peek().isdigit():
            self.pos += 1
        if start == self.pos:
            raise self.error("expected a number")
        return int(self.pattern[start : self.pos])

    def atom(self) -> Node:
        ch = self.take()
        if ch == "(":
            open_at = self.pos - 1
            inner = self.alternation()
            if self.peek() != ")":
                raise self.error("unmatched (", open_at)
            self.pos += 1
            return inner
        if ch == ".":
            return ANY
        if ch == "^":
            return Start()
        if ch == "$":
            return End()
        if ch == "[":
            return self.char_class()
        if ch == "\\":
            return self.escape()
        if ch in SPECIAL:
            raise self.error("nothing to repeat" if ch in "*+?{" else f"{ch} must be escaped",
                             self.pos - 1)
        return Char(((ch, ch),))

    def escape(self) -> Char:
        ch = self.take()
        if ch == "d":
            return Char(DIGIT)
        if ch == "w":
            return Char(WORD)
        if ch in ESCAPABLE:
            return Char(((ch, ch),))
        raise self.error(f"unknown escape \\{ch}", self.pos - 2)

    def char_class(self) -> Char:
        open_at = self.pos - 1
        negated = self.peek() == "^"
        if negated:
            self.pos += 1
        ranges: list[tuple[str, str]] = []
        first = True
        while True:
            if self.peek() is None:
                raise self.error("unterminated [", open_at)
            if self.peek() == "]":
                if first:
                    raise self.error("a class needs at least one character")
                self.pos += 1
                break
            first = False
            item = self.class_item()
            at_range = (
                self.peek() == "-"
                and self.pos + 1 < len(self.pattern)
                and self.pattern[self.pos + 1] != "]"
            )
            if at_range:
                if len(item) != 1 or item[0][0] != item[0][1]:
                    raise self.error("a range needs single characters at both ends")
                self.pos += 1
                end = self.class_item()
                if len(end) != 1 or end[0][0] != end[0][1]:
                    raise self.error("a range needs single characters at both ends")
                low, high = item[0][0], end[0][0]
                if low > high:
                    raise self.error(f"bad range {low}-{high}")
                ranges.append((low, high))
            else:
                ranges.extend(item)
        return Char(tuple(ranges), negated)

    def class_item(self) -> tuple[tuple[str, str], ...]:
        ch = self.take()
        if ch == "\\":
            return self.escape().ranges
        if ch == "[":
            raise self.error("[ inside a class must be escaped", self.pos - 1)
        return ((ch, ch),)
