"""RSS 2.0 feeds: the wiki's recent changes, and the revisions of one page."""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from .changes import describe
from .clock import rfc822
from .errors import PageNotFound
from .models import Change

if TYPE_CHECKING:
    from .wiki import Wiki


def page_url(wiki: Wiki, slug: str) -> str:
    return f"{wiki.settings.base_url.rstrip('/')}/pages/{slug}.html"


def _channel(wiki: Wiki, title: str, description: str) -> tuple[ET.Element, ET.Element]:
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = wiki.settings.base_url
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "generator").text = "leafwiki"
    return rss, channel


def _serialise(rss: ET.Element) -> str:
    ET.indent(rss)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n"


def _item_link(wiki: Wiki, change: Change) -> str | None:
    """The page's address under its current title; None once the page is gone."""
    try:
        slug = wiki.page_by_id(change.page_id).slug
    except PageNotFound:
        return None
    return page_url(wiki, slug)


def changes_feed(wiki: Wiki, limit: int | None = None) -> str:
    """The recent changes as RSS, newest first."""
    site = wiki.settings.site_name
    rss, channel = _channel(wiki, f"{site}: recent changes", f"What changed on {site}")
    for change in wiki.recent_changes(limit or wiki.settings.feed_items):
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{change.title}: {change.kind}"
        link = _item_link(wiki, change)
        if link is not None:
            ET.SubElement(item, "link").text = link
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = f"{wiki.settings.base_url.rstrip('/')}/changes/{change.seq}"
        ET.SubElement(item, "pubDate").text = rfc822(change.at)
        ET.SubElement(item, "category").text = change.kind
        ET.SubElement(item, "description").text = describe(change)
    return _serialise(rss)


def page_feed(wiki: Wiki, title: str, limit: int = 20) -> str:
    """One page's revisions as RSS, newest first."""
    page = wiki.page(title)
    rss, channel = _channel(wiki, f"{page.title} ({wiki.settings.site_name})", f"Revisions of {page.title}")
    for revision in reversed(page.revisions[-limit:]):
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{page.title}: revision {revision.number}"
        ET.SubElement(item, "link").text = page_url(wiki, page.slug)
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = f"{page_url(wiki, page.slug)}#r{revision.number}"
        ET.SubElement(item, "pubDate").text = rfc822(revision.at)
        summary = revision.summary or "(no summary)"
        who = f" by {revision.author}" if revision.author else ""
        ET.SubElement(item, "description").text = f"{summary}{who}"
    return _serialise(rss)
