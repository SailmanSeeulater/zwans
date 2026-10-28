"""A small template language.

{{ post.title }}                  a value, HTML-escaped
{{ post.date|date }}              filters, see filters.py; `|safe` skips escaping
{{ text|truncate:20 }}            a filter with an argument
{% if x %}...{% elif y %}...{% else %}...{% endif %}
{% for post in posts %}...{% else %}(when empty){% endfor %}   loop.index, loop.first, loop.last
{% include "header.html" %}
{# a comment #}
"""

import hashlib
import html
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sitegen.filters import FILTERS, Markup


class TemplateError(Exception):
    pass


_TOKEN = re.compile(r"({{.*?}}|{%.*?%}|{#.*?#})", re.DOTALL)
_FOR = re.compile(r"^for\s+(\w+)\s+in\s+(.+)$")


# --- expressions -----------------------------------------------------------------


@dataclass
class Expression:
    source: str
    path: list[str]
    literal: object = None
    is_literal: bool = False
    negate: bool = False
    filters: list[tuple[str, object]] = field(default_factory=list)

    def evaluate(self, context: "Context") -> object:
        value = self.literal if self.is_literal else context.lookup(self.path)
        for name, argument in self.filters:
            function = FILTERS.get(name)
            if function is None:
                raise TemplateError(f"unknown filter {name!r} in {{{{ {self.source} }}}}")
            if argument is None:
                value = function(value, context.settings)
            else:
                value = function(value, context.settings, argument)
        return (not value) if self.negate else value


def _literal(text: str) -> tuple[bool, object]:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return True, text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return True, int(text)
    return False, None


def parse_expression(source: str) -> Expression:
    text = source.strip()
    negate = False
    if text.startswith("not "):
        negate, text = True, text[4:].strip()
    head, *filter_parts = [part.strip() for part in text.split("|")]
    if not head:
        raise TemplateError(f"empty expression: {source!r}")
    filters: list[tuple[str, object]] = []
    for part in filter_parts:
        name, _, raw = part.partition(":")
        argument: object = None
        if raw:
            is_literal, value = _literal(raw.strip())
            if not is_literal:
                raise TemplateError(f"filter arguments must be literals: {part!r}")
            argument = value
        filters.append((name.strip(), argument))
    is_literal, literal = _literal(head)
    path = [] if is_literal else head.split(".")
    if not is_literal and not all(re.fullmatch(r"\w+", piece) for piece in path):
        raise TemplateError(f"bad expression: {source!r}")
    return Expression(source, path, literal, is_literal, negate, filters)


# --- nodes -----------------------------------------------------------------------


class Node:
    def render(self, context: "Context", out: list[str]) -> None:
        raise NotImplementedError


@dataclass
class Text(Node):
    text: str

    def render(self, context: "Context", out: list[str]) -> None:
        out.append(self.text)


@dataclass
class Output(Node):
    expression: Expression

    def render(self, context: "Context", out: list[str]) -> None:
        value = self.expression.evaluate(context)
        if value is None:
            return
        if isinstance(value, Markup):
            out.append(str(value))
        else:
            out.append(html.escape(str(value)))


@dataclass
class If(Node):
    branches: list[tuple[Expression | None, list[Node]]]

    def render(self, context: "Context", out: list[str]) -> None:
        for condition, body in self.branches:
            if condition is None or condition.evaluate(context):
                for node in body:
                    node.render(context, out)
                return


@dataclass
class Loop:
    index: int
    length: int

    @property
    def first(self) -> bool:
        return self.index == 1

    @property
    def last(self) -> bool:
        return self.index == self.length


@dataclass
class For(Node):
    name: str
    iterable: Expression
    body: list[Node]
    empty: list[Node]

    def render(self, context: "Context", out: list[str]) -> None:
        value = self.iterable.evaluate(context)
        items = list(value) if isinstance(value, Iterable) and value is not None else []
        if not items:
            for node in self.empty:
                node.render(context, out)
            return
        for index, item in enumerate(items, start=1):
            inner = context.child({self.name: item, "loop": Loop(index, len(items))})
            for node in self.body:
                node.render(inner, out)


@dataclass
class Include(Node):
    name: str

    def render(self, context: "Context", out: list[str]) -> None:
        template = context.engine.get(self.name)
        for node in template.nodes:
            node.render(context, out)


# --- parsing ---------------------------------------------------------------------


def _tokens(source: str) -> list[str]:
    return [token for token in _TOKEN.split(source) if token]


def parse(source: str, name: str = "<string>") -> list[Node]:
    tokens = _tokens(source)
    position = 0

    def block(stop: tuple[str, ...]) -> tuple[list[Node], str | None]:
        nonlocal position
        nodes: list[Node] = []
        while position < len(tokens):
            token = tokens[position]
            position += 1
            if token.startswith("{#"):
                continue
            if token.startswith("{{"):
                nodes.append(Output(parse_expression(token[2:-2])))
                continue
            if not token.startswith("{%"):
                nodes.append(Text(token))
                continue
            tag = token[2:-2].strip()
            keyword = tag.split(None, 1)[0] if tag else ""
            if keyword in stop:
                return nodes, tag
            if keyword == "if":
                nodes.append(parse_if(tag[2:].strip()))
            elif keyword == "for":
                nodes.append(parse_for(tag))
            elif keyword == "include":
                is_literal, value = _literal(tag[len("include") :].strip())
                if not is_literal or not isinstance(value, str):
                    raise TemplateError(f"{name}: include needs a quoted template name")
                nodes.append(Include(value))
            else:
                raise TemplateError(f"{name}: unexpected {{% {tag} %}}")
        if stop:
            raise TemplateError(f"{name}: missing {{% {stop[-1]} %}}")
        return nodes, None

    def parse_if(condition: str) -> If:
        branches: list[tuple[Expression | None, list[Node]]] = []
        current: Expression | None = parse_expression(condition)
        while True:
            body, tag = block(("elif", "else", "endif"))
            branches.append((current, body))
            assert tag is not None
            if tag == "endif":
                return If(branches)
            if tag == "else":
                body, tag = block(("endif",))
                branches.append((None, body))
                return If(branches)
            current = parse_expression(tag[4:])

    def parse_for(tag: str) -> For:
        match = _FOR.match(tag)
        if not match:
            raise TemplateError(f"{name}: bad loop {{% {tag} %}}")
        body, end = block(("else", "endfor"))
        empty: list[Node] = []
        if end == "else":
            empty, _ = block(("endfor",))
        return For(match.group(1), parse_expression(match.group(2)), body, empty)

    nodes, _ = block(())
    return nodes


# --- running ---------------------------------------------------------------------


class Context:
    def __init__(
        self,
        engine: "Engine",
        values: dict[str, object],
        settings: object,
        parent: "Context | None" = None,
    ) -> None:
        self.engine = engine
        self.values = values
        self.settings = settings
        self.parent = parent

    def child(self, values: dict[str, object]) -> "Context":
        return Context(self.engine, values, self.settings, self)

    def lookup(self, path: list[str]) -> object:
        context: Context | None = self
        while context is not None and path[0] not in context.values:
            context = context.parent
        if context is None:
            return None
        value = context.values[path[0]]
        for piece in path[1:]:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(piece)
            else:
                value = getattr(value, piece, None)
            if callable(value) and not isinstance(value, type):
                value = value()
        return value


@dataclass
class Template:
    name: str
    source: str
    nodes: list[Node]


class Engine:
    """Finds templates in the site's templates folder, falling back to the built-in theme."""

    def __init__(self, folder: Path | None, builtin: dict[str, str], settings: object) -> None:
        self.folder = folder
        self.builtin = builtin
        self.settings = settings
        # TODO: this cache is never emptied, so a long `sitegen serve` session keeps
        # every template it ever compiled.
        self._compiled: dict[tuple[str, str], Template] = {}

    def source(self, name: str) -> str:
        if self.folder is not None:
            path = self.folder / name
            if path.is_file():
                return path.read_text(encoding="utf-8")
        if name in self.builtin:
            return self.builtin[name]
        raise TemplateError(f"no template called {name!r}")

    def get(self, name: str) -> Template:
        source = self.source(name)
        key = (name, hashlib.sha256(source.encode("utf-8")).hexdigest())
        if key not in self._compiled:
            self._compiled[key] = Template(name, source, parse(source, name))
        return self._compiled[key]

    def names(self) -> list[str]:
        names = set(self.builtin)
        if self.folder is not None and self.folder.is_dir():
            names.update(path.name for path in self.folder.glob("*.html"))
        return sorted(names)

    def fingerprint(self) -> str:
        """Changes whenever any template changes."""
        digest = hashlib.sha256()
        for name in self.names():
            digest.update(name.encode("utf-8") + b"\0" + self.source(name).encode("utf-8"))
        return digest.hexdigest()[:16]

    def render(self, name: str, values: dict[str, object]) -> str:
        template = self.get(name)
        out: list[str] = []
        context = Context(self, values, self.settings)
        for node in template.nodes:
            node.render(context, out)
        return "".join(out)


RenderFunction = Callable[[], str]
