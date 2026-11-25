"""HTML scaffolding for the static export."""

from __future__ import annotations

from html import escape

STYLE = """\
body { font: 16px/1.5 system-ui, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #222; }
header, footer { color: #666; font-size: 0.9rem; }
header a { margin-right: 1rem; }
a.wikilink.missing { color: #b00; }
.tags a { background: #eef; padding: 0 0.4rem; border-radius: 0.3rem; margin-right: 0.3rem; }
.backlinks, .attachments { border-top: 1px solid #ddd; margin-top: 2rem; padding-top: 0.5rem; }
.cloud a { margin-right: 0.6rem; }
.cloud .s1 { font-size: 0.9rem; } .cloud .s2 { font-size: 1rem; } .cloud .s3 { font-size: 1.2rem; }
.cloud .s4 { font-size: 1.4rem; } .cloud .s5 { font-size: 1.7rem; }
pre { background: #f6f6f6; padding: 0.6rem; overflow-x: auto; }
"""


def document(title: str, site: str, body: str, root: str = "") -> str:
    """A full page. ``root`` is the relative path back to the export's top folder."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · {escape(site)}</title>
<link rel="stylesheet" href="{root}style.css">
</head>
<body>
<header><a href="{root}index.html">{escape(site)}</a><a href="{root}tags/index.html">Tags</a><a href="{root}recent.html">Recent changes</a></header>
<main>
<h1>{escape(title)}</h1>
{body}
</main>
<footer>Exported by leafwiki</footer>
</body>
</html>
"""


def link_list(items: list[tuple[str, str]], css: str = "") -> str:
    """<ul> of (href, text) pairs."""
    if not items:
        return "<p>Nothing here yet.</p>"
    cls = f' class="{css}"' if css else ""
    rows = "".join(f'<li><a href="{escape(h)}">{escape(t)}</a></li>' for h, t in items)
    return f"<ul{cls}>{rows}</ul>"
