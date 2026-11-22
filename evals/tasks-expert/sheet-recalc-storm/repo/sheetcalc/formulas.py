"""Formulas: parsing them, finding the cells they reference, and evaluating them.

A formula is parsed into nested tuples:

    ("num", 2.0)                     a number
    ("ref", "B3")                    one cell
    ("range", "A1", "B3")            a block of cells, only as a function argument
    ("neg", node)                    unary minus
    ("bin", "+", left, right)        + - * / = <> < > <= >=
    ("call", "SUM", [node, ...])     SUM MIN MAX COUNT IF
"""

import re
from collections.abc import Callable

Node = tuple  # see the module docstring
Value = float | str | None  # None is a blank cell; an Error is a str too


class Error(str):
    """An error value such as #DIV/0!. A str, so it prints as its code, but its own type, so
    a cell holding the text "#DIV/0!" isn't one."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Error({str.__repr__(self)})"


DIV0 = Error("#DIV/0!")
VALUE = Error("#VALUE!")
CYCLE = Error("#CYCLE!")
PARSE = Error("#PARSE!")

CELL = re.compile(r"^([A-Z])([1-9][0-9]{0,3})$")
TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z]+[0-9]*)|(?P<op><>|<=|>=|[-+*/()=<>,:]))"
)
FUNCTIONS = {"SUM", "MIN", "MAX", "COUNT", "IF"}
COMPARISONS = {"=", "<>", "<", ">", "<=", ">="}


class FormulaError(Exception):
    """The text isn't a formula this engine understands."""


def normalize(cell: str) -> str:
    """A cell's name in its one spelling ("b3" -> "B3"). Raises ValueError for anything that
    isn't a column A-Z followed by a row 1-9999."""
    name = cell.strip().upper()
    if not CELL.match(name):
        raise ValueError(f"{cell!r} isn't a cell name")
    return name


def cells_in(first: str, last: str) -> list[str]:
    """The cells of the block with corners `first` and `last`, row by row."""
    (c1, r1), (c2, r2) = _split(first), _split(last)
    columns = range(min(c1, c2), max(c1, c2) + 1)
    rows = range(min(r1, r2), max(r1, r2) + 1)
    return [f"{chr(column)}{row}" for row in rows for column in columns]


def _split(cell: str) -> tuple[int, int]:
    match = CELL.match(cell)
    assert match is not None
    return ord(match.group(1)), int(match.group(2))


# -- parsing


def parse(text: str) -> Node:
    """Parse a formula's text, without its leading "=". Raises FormulaError."""
    tokens = _tokens(text)
    parser = _Parser(tokens)
    node = parser.comparison()
    if parser.peek() is not None:
        raise FormulaError(f"unexpected {parser.peek()!r}")
    return node


def _tokens(text: str) -> list[str]:
    tokens, position = [], 0
    text = text.rstrip()
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None:
            raise FormulaError(f"can't read {text[position:]!r}")
        tokens.append(match.group(match.lastgroup or 0))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise FormulaError("the formula ends early")
        self.position += 1
        return token

    def expect(self, token: str) -> None:
        if self.take() != token:
            raise FormulaError(f"expected {token!r}")

    def comparison(self) -> Node:
        left = self.sum()
        if self.peek() in COMPARISONS:
            op = self.take()
            return ("bin", op, left, self.sum())
        return left

    def sum(self) -> Node:
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            node = ("bin", op, node, self.term())
        return node

    def term(self) -> Node:
        node = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            node = ("bin", op, node, self.unary())
        return node

    def unary(self) -> Node:
        if self.peek() == "-":
            self.take()
            return ("neg", self.unary())
        return self.atom()

    def atom(self) -> Node:
        token = self.take()
        if token == "(":
            node = self.comparison()
            self.expect(")")
            return node
        if token[0].isdigit():
            return ("num", float(token))
        name = token.upper()
        if name in FUNCTIONS:
            return self.call(name)
        if CELL.match(name):
            return ("ref", name)
        raise FormulaError(f"unexpected {token!r}")

    def call(self, name: str) -> Node:
        self.expect("(")
        args = [self.argument(ranges=name != "IF")]
        while self.peek() == ",":
            self.take()
            args.append(self.argument(ranges=name != "IF"))
        self.expect(")")
        if name == "IF" and len(args) != 3:
            raise FormulaError("IF takes a condition and two values")
        return ("call", name, args)

    def argument(self, ranges: bool) -> Node:
        node = self.comparison()
        if self.peek() == ":":
            self.take()
            last = self.atom()
            if not ranges or node[0] != "ref" or last[0] != "ref":
                raise FormulaError("a range is two cells, as A1:B3, inside SUM, MIN, MAX or COUNT")
            return ("range", node[1], last[1])
        return node


# -- references


def references(node: Node) -> set[str]:
    """Every cell the formula mentions, ranges spelled out, whether or not evaluating it
    would read them (both branches of an IF count)."""
    kind = node[0]
    if kind == "ref":
        return {node[1]}
    if kind == "range":
        return set(cells_in(node[1], node[2]))
    if kind == "neg":
        return references(node[1])
    if kind == "bin":
        return references(node[2]) | references(node[3])
    if kind == "call":
        found: set[str] = set()
        for arg in node[2]:
            found |= references(arg)
        return found
    return set()


# -- evaluating


def evaluate(node: Node, lookup: Callable[[str], Value]) -> Value:
    """The formula's value, reading other cells' values through `lookup`. Never raises: what
    goes wrong comes back as an Error. See the README for the rules."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return _number(lookup(node[1]))
    if kind == "neg":
        value = evaluate(node[1], lookup)
        return value if isinstance(value, Error) else -_as_float(value)
    if kind == "bin":
        return _binary(node[1], evaluate(node[2], lookup), lambda: evaluate(node[3], lookup))
    if kind == "call":
        return _call(node[1], node[2], lookup)
    raise AssertionError(f"a range can't be evaluated on its own: {node!r}")


def _number(value: Value) -> Value:
    """A cell's value as a formula operand: blank is 0, text is #VALUE!."""
    if value is None:
        return 0.0
    if isinstance(value, Error) or isinstance(value, float):
        return value
    return VALUE


def _as_float(value: Value) -> float:
    assert isinstance(value, float)
    return value


def _binary(op: str, left: Value, right_of: Callable[[], Value]) -> Value:
    if isinstance(left, Error):
        return left  # the first error, reading left to right
    right = right_of()
    if isinstance(right, Error):
        return right
    a, b = _as_float(left), _as_float(right)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return DIV0 if b == 0 else a / b
    truth = {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    return 1.0 if truth else 0.0


def _call(name: str, args: list[Node], lookup: Callable[[str], Value]) -> Value:
    if name == "IF":
        condition = evaluate(args[0], lookup)
        if isinstance(condition, Error):
            return condition
        return evaluate(args[1] if condition != 0 else args[2], lookup)  # only the branch taken
    numbers: list[float] = []
    for arg in args:
        if arg[0] == "range":
            for cell in cells_in(arg[1], arg[2]):
                value = lookup(cell)
                if isinstance(value, Error):
                    return value
                if isinstance(value, float):  # blank cells and text are left out
                    numbers.append(value)
        else:
            value = evaluate(arg, lookup)
            if isinstance(value, Error):
                return value
            numbers.append(_as_float(value))
    if name == "SUM":
        return float(sum(numbers))
    if name == "COUNT":
        return float(len(numbers))
    if not numbers:
        return 0.0
    return min(numbers) if name == "MIN" else max(numbers)


def literal(text: str) -> Value:
    """What a cell holds when its text isn't a formula: a number if it reads as one."""
    try:
        return float(text)
    except ValueError:
        return text
