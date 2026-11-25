"""sitemap.xml for the exported site, so search engines find every page."""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from .feeds import page_url

if TYPE_CHECKING:
    from .wiki import Wiki

NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def sitemap_xml(wiki: Wiki) -> str:
    """One <url> per page with its address and the date it last changed."""
    urlset = ET.Element("urlset", xmlns=NAMESPACE)
    front = wiki.settings.front_page
    pages = wiki.pages()
    pages.sort(key=lambda p: 0 if p.title == front else 1)  # stable: the rest stay by title
    for page in pages:
        url = ET.SubElement(urlset, "url")
        ET.SubElement(url, "loc").text = page_url(wiki, page.slug)
        ET.SubElement(url, "lastmod").text = page.updated_at[:10]
        ET.SubElement(url, "priority").text = "1.0" if page.title == front else "0.5"
    ET.indent(urlset)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(urlset, encoding="unicode") + "\n"


def sitemap_urls(xml: str) -> list[str]:
    """The addresses listed in a sitemap (handy for checking an export)."""
    root = ET.fromstring(xml)
    return [loc.text or "" for loc in root.iter(f"{{{NAMESPACE}}}loc")]
