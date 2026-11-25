"""leafwiki's markup language: parsing, rendering, link extraction, plain text."""

from .blocks import Block, inline_texts, parse_blocks
from .html import render_html, table_of_contents
from .inline import WikiLink, parse_inline, plain, walk


def extract_links(source: str) -> list[WikiLink]:
    """The page links in a text, first occurrence of each target only, in order.

    Links inside code spans and code blocks don't count.
    """
    seen: set[str] = set()
    links: list[WikiLink] = []
    for text in inline_texts(parse_blocks(source)):
        for node in walk(parse_inline(text)):
            if isinstance(node, WikiLink) and node.slug not in seen:
                seen.add(node.slug)
                links.append(node)
    return links


def plain_text(source: str) -> str:
    """The readable text of a page: markup stripped, code blocks kept as they are."""
    parts: list[str] = []
    for block in parse_blocks(source):
        if block.kind == "code":
            parts.append(block.text)
        elif block.kind in ("bullets", "numbers"):
            parts.extend(plain(parse_inline(item)) for item in block.items)
        elif block.kind != "rule":
            parts.append(plain(parse_inline(block.text)))
    return "\n".join(parts)


__all__ = [
    "Block",
    "WikiLink",
    "extract_links",
    "parse_blocks",
    "plain_text",
    "render_html",
    "table_of_contents",
]
