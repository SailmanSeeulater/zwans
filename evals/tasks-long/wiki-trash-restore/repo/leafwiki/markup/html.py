"""Render leafwiki markup to HTML.

Links to pages go through two callbacks, so the same renderer serves the live wiki (links
like ``/pages/front-page``) and the static export (``front-page.html``):

* ``href(slug)`` gives the address of a page,
* ``exists(slug)`` says whether the page is there. Links to pages that don't exist get the
  extra class ``missing`` so a stylesheet can show them in red.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from .blocks import Block, parse_blocks
from .inline import Code, Emphasis, Node, Strong, Text, WebLink, WikiLink, parse_inline
from ..textutil import slugify

Href = Callable[[str], str]
Exists = Callable[[str], bool]


def _default_href(slug: str) -> str:
    return f"/pages/{slug}"


def _always(slug: str) -> bool:
    return True


def render_inline(nodes: list[Node] | tuple, href: Href, exists: Exists) -> str:
    out: list[str] = []
    for node in nodes:
        if isinstance(node, Text):
            out.append(escape(node.text, quote=False))
        elif isinstance(node, Code):
            out.append(f"<code>{escape(node.text, quote=False)}</code>")
        elif isinstance(node, Strong):
            out.append(f"<strong>{render_inline(node.children, href, exists)}</strong>")
        elif isinstance(node, Emphasis):
            out.append(f"<em>{render_inline(node.children, href, exists)}</em>")
        elif isinstance(node, WikiLink):
            classes = "wikilink" if exists(node.slug) else "wikilink missing"
            out.append(
                f'<a class="{classes}" href="{escape(href(node.slug))}">'
                f"{escape(node.label, quote=False)}</a>"
            )
        elif isinstance(node, WebLink):
            out.append(
                f'<a class="external" href="{escape(node.url)}" rel="nofollow">'
                f"{escape(node.label, quote=False)}</a>"
            )
    return "".join(out)


def _anchor(text: str) -> str:
    return "h-" + slugify(text)


def render_block(block: Block, href: Href, exists: Exists) -> str:
    def inline(text: str) -> str:
        return render_inline(parse_inline(text), href, exists)

    if block.kind == "heading":
        level = block.level + 1  # the page title is the <h1>
        return f'<h{level} id="{_anchor(block.text)}">{inline(block.text)}</h{level}>'
    if block.kind == "paragraph":
        return f"<p>{inline(block.text)}</p>"
    if block.kind == "quote":
        return f"<blockquote><p>{inline(block.text)}</p></blockquote>"
    if block.kind == "rule":
        return "<hr>"
    if block.kind == "code":
        language = f' class="language-{escape(block.language)}"' if block.language else ""
        return f"<pre><code{language}>{escape(block.text, quote=False)}</code></pre>"
    tag = "ul" if block.kind == "bullets" else "ol"
    items = "".join(f"<li>{inline(item)}</li>" for item in block.items)
    return f"<{tag}>{items}</{tag}>"


def render_html(source: str, href: Href | None = None, exists: Exists | None = None) -> str:
    href = href or _default_href
    exists = exists or _always
    return "\n".join(render_block(block, href, exists) for block in parse_blocks(source))


def table_of_contents(source: str) -> list[tuple[int, str, str]]:
    """(level, text, anchor) for every heading, for pages long enough to want one."""
    return [
        (block.level, block.text, _anchor(block.text))
        for block in parse_blocks(source)
        if block.kind == "heading"
    ]
