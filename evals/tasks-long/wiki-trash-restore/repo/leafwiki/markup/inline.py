"""Inline markup: wiki links, web links, emphasis and code spans.

* ``[[Page title]]`` links to a page; ``[[Page title|shown text]]`` shows other text
* ``[shown text](https://example.com)`` links to the web
* ``**strong**``, ``*emphasis*``, ```code```
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..textutil import slugify


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Strong:
    children: tuple


@dataclass(frozen=True)
class Emphasis:
    children: tuple


@dataclass(frozen=True)
class Code:
    text: str


@dataclass(frozen=True)
class WikiLink:
    target: str
    label: str

    @property
    def slug(self) -> str:
        return slugify(self.target)


@dataclass(frozen=True)
class WebLink:
    url: str
    label: str


Node = Text | Strong | Emphasis | Code | WikiLink | WebLink

_TOKEN = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<wiki>\[\[[^\[\]]+\]\])"
    r"|(?P<web>\[[^\[\]]+\]\((?:https?|mailto):[^)\s]+\))"
    r"|(?P<strong>\*\*(?=\S)(?:.+?)(?<=\S)\*\*)"
    r"|(?P<em>\*(?=\S)(?:[^*]+?)(?<=\S)\*)"
)
_WEB = re.compile(r"^\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)$")


def parse_inline(text: str) -> list[Node]:
    nodes: list[Node] = []
    position = 0
    for match in _TOKEN.finditer(text):
        if match.start() > position:
            nodes.append(Text(text[position : match.start()]))
        token = match.group(0)
        kind = match.lastgroup
        if kind == "code":
            nodes.append(Code(token[1:-1]))
        elif kind == "wiki":
            inner = token[2:-2]
            target, _, label = inner.partition("|")
            target = " ".join(target.split())
            label = " ".join(label.split()) or target
            if target:
                nodes.append(WikiLink(target, label))
            else:
                nodes.append(Text(token))
        elif kind == "web":
            web = _WEB.match(token)
            assert web is not None
            nodes.append(WebLink(web.group("url"), web.group("label")))
        elif kind == "strong":
            nodes.append(Strong(tuple(parse_inline(token[2:-2]))))
        else:
            nodes.append(Emphasis(tuple(parse_inline(token[1:-1]))))
        position = match.end()
    if position < len(text):
        nodes.append(Text(text[position:]))
    return nodes


def walk(nodes: list[Node] | tuple) -> list[Node]:
    """Every node, depth first, including the ones inside emphasis."""
    out: list[Node] = []
    for node in nodes:
        out.append(node)
        if isinstance(node, Strong | Emphasis):
            out.extend(walk(node.children))
    return out


def plain(nodes: list[Node] | tuple) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, Text | Code):
            parts.append(node.text)
        elif isinstance(node, WikiLink | WebLink):
            parts.append(node.label)
        else:
            parts.append(plain(node.children))
    return "".join(parts)
