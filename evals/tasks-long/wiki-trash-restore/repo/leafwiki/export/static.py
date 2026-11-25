"""Export the wiki as a static website: plain HTML files any web server can serve.

Layout of the output folder::

    index.html                 every page, by title (the front page first)
    pages/<slug>.html          one file per page
    files/<slug>/<name>        the attachments of each page
    tags/index.html            every tag, sized by use
    tags/<tag>.html            the pages carrying a tag
    recent.html                recent changes, grouped by day
    sitemap.xml                see leafwiki.sitemap
    style.css
"""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from ..attachments import human_size
from ..changes import describe
from ..errors import PageNotFound
from ..sitemap import sitemap_xml
from ..tags import tag_cloud
from .templates import STYLE, document, link_list

if TYPE_CHECKING:
    from ..models import Page
    from ..wiki import Wiki


class Writer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.written: list[str] = []

    def text(self, relative: str, content: str) -> None:
        self.data(relative, content.encode("utf-8"))

    def data(self, relative: str, content: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.written.append(relative)


def _page_body(wiki: Wiki, page: Page) -> str:
    parts = [wiki.render(page.title, href=lambda slug: f"{quote(slug)}.html")]
    if page.tags:
        tags = "".join(
            f'<a href="../tags/{quote(tag)}.html">{escape(tag)}</a>' for tag in page.tags
        )
        parts.append(f'<p class="tags">{tags}</p>')
    if page.attachments:
        rows = "".join(
            f'<li><a href="../files/{quote(page.slug)}/{quote(a.name)}">{escape(a.name)}</a>'
            f" ({human_size(a.size)})</li>"
            for a in page.attachments.values()
        )
        parts.append(f'<div class="attachments"><h2>Attachments</h2><ul>{rows}</ul></div>')
    backlinks = wiki.backlinks(page.title)
    if backlinks:
        items = [(f"{quote(wiki.page(t).slug)}.html", t) for t in backlinks]
        parts.append(f'<div class="backlinks"><h2>Linked from</h2>{link_list(items)}</div>')
    who = f" by {escape(page.last_author)}" if page.last_author else ""
    parts.append(f"<p><small>Revision {page.current.number}, {page.updated_at[:10]}{who}</small></p>")
    return "\n".join(parts)


def _recent(wiki: Wiki) -> str:
    sections: list[str] = []
    for day, changes in wiki.changes.by_day(100):
        rows: list[str] = []
        for change in changes:
            line = escape(describe(change)[11:])
            try:
                target = wiki.page_by_id(change.page_id)
            except PageNotFound:
                rows.append(f"<li>{line}</li>")
                continue
            rows.append(f'<li><a href="pages/{quote(target.slug)}.html">{line}</a></li>')
        sections.append(f"<h2>{day}</h2><ul>{''.join(rows)}</ul>")
    return "\n".join(sections) or "<p>Nothing has changed yet.</p>"


def export_site(wiki: Wiki, out_dir: str | Path, clean: bool = True) -> list[str]:
    """Write the site into ``out_dir``. Returns the files written, relative to it."""
    root = Path(out_dir)
    if clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    out = Writer(root)
    site = wiki.settings.site_name
    pages = wiki.pages()

    front = wiki.settings.front_page
    ordered = sorted(pages, key=lambda p: 0 if p.title == front else 1)
    index_items = [(f"pages/{quote(p.slug)}.html", p.title) for p in ordered]
    out.text("index.html", document(site, site, link_list(index_items, "pages")))

    for page in pages:
        out.text(f"pages/{page.slug}.html", document(page.title, site, _page_body(wiki, page), "../"))
        for attachment in page.attachments.values():
            out.data(f"files/{page.slug}/{attachment.name}", wiki.attachment(page.title, attachment.name))

    counts = wiki.tags()
    sizes = tag_cloud(counts)
    cloud = " ".join(
        f'<a class="s{sizes[tag]}" href="{quote(tag)}.html">{escape(tag)}</a> ({count})'
        for tag, count in counts.items()
    )
    out.text("tags/index.html", document("Tags", site, f'<p class="cloud">{cloud}</p>', "../"))
    for tag in counts:
        items = [(f"../pages/{quote(wiki.page(t).slug)}.html", t) for t in wiki.pages_tagged(tag)]
        out.text(f"tags/{tag}.html", document(f"Tagged {tag}", site, link_list(items), "../"))

    out.text("recent.html", document("Recent changes", site, _recent(wiki)))
    out.text("sitemap.xml", sitemap_xml(wiki))
    out.text("style.css", STYLE)
    return out.written
