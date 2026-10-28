"""The built-in theme. A site overrides any of these by putting a file with the same
name in its templates/ folder."""

HEAD = """<!doctype html>
<html lang="{{ site.language }}">
<head>
<meta charset="utf-8">
<title>{% if title %}{{ title }} - {% endif %}{{ site.title }}</title>
<link rel="alternate" type="application/atom+xml" href="{{ 'feed.xml'|url }}">
</head>
<body>
<header><a href="{{ ''|url }}">{{ site.title }}</a>
<nav><a href="{{ 'archive/'|url }}">Archive</a> <a href="{{ 'tags/'|url }}">Tags</a></nav></header>
<main>
"""

FOOT = """</main>
<footer>{% if site.author %}&copy; {{ site.author }}{% endif %}</footer>
</body>
</html>
"""

SUMMARY = """<article class="summary">
<h2><a href="{{ s.url|url }}">{{ s.title }}</a></h2>
<p class="meta"><time datetime="{{ s.date|isodate }}">{{ s.date|date }}</time>
 · {{ s.reading_minutes }} min{% if s.tags %} · {% for tag in s.tags %}<a href="{{ tag.url|url }}">{{ tag.name }}</a>{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}</p>
<div class="excerpt">{{ s.excerpt|safe }}</div>
</article>
"""

POST = """{% include "head.html" %}<article>
<h1>{{ page.title }}</h1>
<p class="meta"><time datetime="{{ page.date|isodate }}">{{ page.date|date }}</time>
{% for tag in tags %}<a href="{{ tag.url|url }}">{{ tag.name }}</a> {% endfor %}</p>
{{ content|safe }}
</article>
{% include "foot.html" %}"""

PAGE = """{% include "head.html" %}<article>
<h1>{{ page.title }}</h1>
{{ content|safe }}
</article>
{% include "foot.html" %}"""

LIST = """{% include "head.html" %}{% if heading %}<h1>{{ heading }}</h1>
{% endif %}{% for s in summaries %}{% include "summary.html" %}{% else %}<p>Nothing here yet.</p>
{% endfor %}<nav class="pager">{% if pager.prev_url %}<a rel="prev" href="{{ pager.prev_url|url }}">Newer</a>{% endif %}
{% if pager.next_url %}<a rel="next" href="{{ pager.next_url|url }}">Older</a>{% endif %}</nav>
{% include "foot.html" %}"""

ARCHIVE = """{% include "head.html" %}<h1>Archive</h1>
{% for year in years %}<h2>{{ year.year }}</h2>
<ul>
{% for s in year.summaries %}<li><time datetime="{{ s.date|isodate }}">{{ s.date|date }}</time> <a href="{{ s.url|url }}">{{ s.title }}</a></li>
{% endfor %}</ul>
{% endfor %}{% include "foot.html" %}"""

TAGS = """{% include "head.html" %}<h1>Tags</h1>
<ul>
{% for tag in tags %}<li><a href="{{ tag.url|url }}">{{ tag.name }}</a> ({{ tag.count|plural:"post" }})</li>
{% endfor %}</ul>
{% include "foot.html" %}"""

TEMPLATES = {
    "head.html": HEAD,
    "foot.html": FOOT,
    "summary.html": SUMMARY,
    "post.html": POST,
    "page.html": PAGE,
    "list.html": LIST,
    "archive.html": ARCHIVE,
    "tags.html": TAGS,
}
