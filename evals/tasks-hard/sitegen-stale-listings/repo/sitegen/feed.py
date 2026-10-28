"""The Atom feed and the sitemap."""

from xml.sax.saxutils import escape, quoteattr

from sitegen.config import Config
from sitegen.summaries import Summary


def atom_date(summary: Summary) -> str:
    return summary.date.strftime("%Y-%m-%dT%H:%M:%SZ")


def render_feed(config: Config, summaries: list[Summary]) -> str:
    """An Atom feed of the given posts, which are already newest first."""
    home = config.absolute_url("")
    updated = atom_date(summaries[0]) if summaries else "1970-01-01T00:00:00Z"
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(config.title)}</title>",
        f"  <link href={quoteattr(home)}/>",
        f'  <link rel="self" href={quoteattr(config.absolute_url("feed.xml"))}/>',
        f"  <id>{escape(home)}</id>",
        f"  <updated>{updated}</updated>",
    ]
    if config.author:
        lines.append(f"  <author><name>{escape(config.author)}</name></author>")
    for summary in summaries:
        url = config.absolute_url(summary.url)
        lines += [
            "  <entry>",
            f"    <title>{escape(summary.title)}</title>",
            f"    <link href={quoteattr(url)}/>",
            f"    <id>{escape(url)}</id>",
            f"    <updated>{atom_date(summary)}</updated>",
        ]
        lines += [f"    <category term={quoteattr(tag.name)}/>" for tag in summary.tags]
        lines += [
            f'    <summary type="html">{escape(summary.excerpt)}</summary>',
            "  </entry>",
        ]
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def render_sitemap(config: Config, urls: list[str]) -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in urls:
        lines.append(f"  <url><loc>{escape(config.absolute_url(url))}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
