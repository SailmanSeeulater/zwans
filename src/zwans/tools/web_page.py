"""A web page as text a model can use (WebFetch, web_local.py).

A page is mostly what surrounds its content: menus, banners, footers. Only the content is
kept, the page's <main> or <article> when it has one. What's left is written as Markdown,
which models read well: headings marked with #, list items with -, code blocks fenced and
kept exactly as written (a docs page's examples are often the reason it was fetched, and
Python without its indentation is broken), tables as Markdown tables, inline code in
backticks, and each link followed by its address so the model can fetch it next.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

SKIPPED = frozenset(
    {"script", "style", "noscript", "svg", "template", "iframe", "head", "nav", "dialog"}
)
SKIPPED_ROLES = frozenset({"navigation", "search", "dialog", "alertdialog"})
# Around a page's content rather than part of it: left out, except inside <main> or <article>,
# where a header holds the title.
FURNITURE = frozenset({"header", "footer", "aside"})
FURNITURE_ROLES = frozenset({"banner", "contentinfo", "complementary"})
VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
    | {"track", "wbr"}
)
BLOCKS = frozenset(
    {"p", "div", "section", "article", "main", "header", "footer", "nav", "aside"}
    | {"ul", "ol", "li", "table", "blockquote", "pre", "figure", "form", "br", "hr"}
    | {"h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd"}
)
HEADINGS = {f"h{level}": "#" * level + " " for level in range(1, 7)}
CELLS = frozenset({"td", "th"})
MIN_CONTENT = 200  # characters a page's <main> needs to be taken as its content
FENCE = "```"
LANGUAGE = re.compile(r"(?:^|\s)(?:language|lang|highlight-source)-([\w+#.-]+)")
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w.:-]+)""", re.IGNORECASE)
# What a page built by JavaScript says, or has, in place of its content.
NEEDS_SCRIPT = re.compile(
    r"enable javascript|javascript is (?:required|disabled)|requires javascript|"
    r'id="(?:root|app|__next|__nuxt)"\s*>\s*</div>',
    re.IGNORECASE,
)
SCRIPT_BODY = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
THIN = 500  # characters of text below which a page may need its JavaScript run
EMPTY_CODE = re.compile(r"(?<!`)`\s*`(?!`)")  # inline code that held nothing


def host_of(url: object) -> str:
    """The host an http or https address names, or "" for anything else."""
    if not isinstance(url, str):
        return ""
    parts = urlsplit(url.strip())
    return (parts.hostname or "").lower() if parts.scheme in ("http", "https") else ""


def charset(content_type: str, body: bytes) -> str:
    """The encoding to read a page with: the header's, else a <meta> tag's, else UTF-8."""
    match = re.search(r"charset=([\w.:-]+)", content_type, re.IGNORECASE)
    name = match.group(1) if match else ""
    if not name:
        meta = META_CHARSET.search(body[:4096])
        name = meta.group(1).decode("ascii", "replace") if meta else ""
    try:
        "".encode(name or "utf-8")
    except LookupError:
        return "utf-8"
    return name or "utf-8"


def needs_script(page: str, text: str) -> bool:
    """Whether a page's content seems to be drawn by its JavaScript, so little of it is in
    the HTML: its text is short, and it says so or is mostly script."""
    if len(text) >= THIN:
        return False
    scripts = sum(len(body) for body in SCRIPT_BODY.findall(page))
    return bool(NEEDS_SCRIPT.search(page)) or scripts > 10 * max(len(text), 50)


@dataclass
class _Region:
    """The text inside one kind of element, as <main>: its tag, how deep in nested elements
    with that tag the parser is (0 outside), and the text."""

    tag: str = ""
    depth: int = 0
    parts: list[str] = field(default_factory=list)
    found: bool = False

    def start(self, tag: str, here: bool) -> None:
        if self.depth and tag == self.tag:
            self.depth += 1
        elif not self.depth and here:
            self.tag, self.depth, self.found = tag, 1, True

    def end(self, tag: str) -> None:
        if self.depth and tag == self.tag:
            self.depth -= 1


class _Table:
    """A table being read: its rows of cells, and the cell being read."""

    def __init__(self) -> None:
        self.rows = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None


class _Text(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts: list[str] = []
        self.main = _Region()
        self.article = _Region()
        self.title = ""
        self.skip_tag = ""  # the element being left out, with what's inside it
        self.skip_depth = 0
        self.in_title = False
        self.link: str | None = None
        self.link_text = ""
        self.pre = 0  # how deep in <pre> elements, where text is kept as it is
        self.fence_open = False  # the current <pre>'s opening fence has been written
        self.language = ""  # of the current <pre>'s code, from a class as language-python
        self.code = 0  # how deep in <code> outside a <pre>
        self.tables: list[_Table] = []

    # -- writing

    def _add(self, text: str) -> None:
        table = self.tables[-1] if self.tables else None
        if table is not None and table.cell is not None:
            table.cell.append(text)
        else:
            self._out(text)
        if self.link:
            self.link_text += text

    def _out(self, text: str) -> None:
        self.parts.append(text)
        for region in (self.main, self.article):
            if region.depth:
                region.parts.append(text)

    def _open_fence(self) -> None:
        if self.pre and not self.fence_open:
            self.fence_open = True
            self._add(f"\n{FENCE}{self.language}\n")

    # -- tables

    def _end_cell(self) -> None:
        table = self.tables[-1]
        if table.cell is None:
            return
        text = " ".join("".join(table.cell).split()).replace("|", "\\|")
        table.cell = None
        if table.row is None:
            table.row = []
        table.row.append(text)

    def _end_row(self) -> None:
        table = self.tables[-1]
        self._end_cell()
        if not table.row:
            table.row = None
            return
        row, table.row = table.row, None
        self._out_row(table, row)

    def _out_row(self, table: _Table, row: list[str]) -> None:
        line = "| " + " | ".join(row) + " |\n"
        if len(self.tables) > 1:  # a table in a cell: its rows run on in the outer cell
            outer = self.tables[-2]
            if outer.cell is not None:
                outer.cell.append(" ".join(row) + " ")
            return
        self._out(("\n" if table.rows == 0 else "") + line)
        if table.rows == 0:
            self._out("|" + " --- |" * len(row) + "\n")
        table.rows += 1

    # -- leaving things out

    def _left_out(self, tag: str, attrs: dict[str, str | None]) -> bool:
        if tag in VOID:
            return False  # nothing inside it, and no end tag to stop at
        role = (attrs.get("role") or "").lower()
        hidden = "hidden" in attrs or (attrs.get("aria-hidden") or "").lower() == "true"
        # A heading's own link, as Sphinx's ¶, is a mark beside it rather than text.
        anchor = tag == "a" and "headerlink" in (attrs.get("class") or "").split()
        if tag in SKIPPED or role in SKIPPED_ROLES or hidden or anchor:
            return True
        outside = not (self.main.depth or self.article.depth)
        return outside and (tag in FURNITURE or role in FURNITURE_ROLES)

    # -- the parser's callbacks

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if self.skip_depth:
            self.skip_depth += tag == self.skip_tag
            return
        named = dict(attrs)
        if self.pre:  # inside code, tags only colour it; a <br> is a line break
            if tag == "code" and not self.fence_open and not self.language:
                self.language = _language(named.get("class"))
            elif tag == "br":
                self._open_fence()
                self._add("\n")
            return
        if self._left_out(tag, named):
            self.skip_tag, self.skip_depth = tag, 1
            return
        role = (named.get("role") or "").lower()
        self.main.start(tag, tag == "main" or role == "main")
        self.article.start(tag, tag == "article" or role == "article")
        if tag == "table":
            self.tables.append(_Table())
            return
        if self.tables and tag == "tr":
            self._end_row()
            return
        if self.tables and tag in CELLS:
            self._end_cell()
            self.tables[-1].cell = []
            return
        if tag in BLOCKS:
            self._add("\n")
        if tag == "pre":
            self.pre, self.fence_open = 1, False
            self.language = _language(named.get("class"))
        elif tag in HEADINGS:
            self._add(HEADINGS[tag])
        elif tag == "li":
            self._add("- ")
        elif tag == "code":
            self.code += 1
            if self.code == 1:
                self._add("`")
        elif tag == "a":
            address = urljoin(self.base, named.get("href") or "")
            # A link within the page, as a heading's own, isn't one to fetch.
            same_page = urldefrag(address).url == urldefrag(self.base).url
            self.link = address if host_of(address) and not same_page else None
            self.link_text = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if self.skip_depth:
            self.skip_depth -= tag == self.skip_tag
            return
        if self.pre:
            if tag != "pre":
                return
            if self.fence_open:
                self._add(f"\n{FENCE}\n")
            self.pre, self.fence_open, self.language = 0, False, ""
            self.main.end(tag)
            self.article.end(tag)
            return
        if tag == "table" and self.tables:
            self._end_row()
            self.tables.pop()
            self._add("\n")
        elif self.tables and tag == "tr":
            self._end_row()
        elif self.tables and tag in CELLS:
            self._end_cell()
        elif tag == "code" and self.code:
            self.code -= 1
            if self.code == 0:
                self._add("`")
        if tag == "a" and self.link:
            link, shown = self.link, self.link_text.strip()
            self.link = None
            if shown and shown != link:
                self._add(f" ({link})")
        if tag in BLOCKS:
            self._add("\n")
        self.main.end(tag)
        self.article.end(tag)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        elif self.skip_depth:
            return
        elif self.pre:
            if not self.fence_open:
                data = data.lstrip("\n")  # the line break after <pre> isn't part of the code
                if not data:
                    return
                self._open_fence()
            self._add(data)
        else:
            self._add(re.sub(r"\s+", " ", data))


def _language(classes: str | None) -> str:
    match = LANGUAGE.search(classes or "")
    return match.group(1).lower() if match else ""


def _tidy(parts: list[str]) -> str:
    """The text with each line's surrounding spaces and runs of blank lines taken out, except
    inside code fences, which stay exactly as they are."""
    out: list[str] = []
    blank = 0
    fenced = False
    for line in "".join(parts).splitlines():
        if line.strip().startswith(FENCE):
            if fenced:
                while out and not out[-1]:  # the code's own last line break
                    out.pop()
            fenced = not fenced
            line = line.strip()
        elif fenced:
            out.append(line.rstrip())
            continue
        else:
            line = re.sub(" {2,}", " ", EMPTY_CODE.sub(" ", line)).strip()
        if not line:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out).strip()


def to_text(page: str, base: str) -> tuple[str, str]:
    """A page's title and its text: its <main>, or else its <article>s, when there's enough
    there to be the content, and otherwise all of it but the menus and the like."""
    parser = _Text(base)
    parser.feed(page)
    parser.close()
    whole = _tidy(parser.parts)
    for region in (parser.main, parser.article):
        text = _tidy(region.parts) if region.found else ""
        if text and (len(text) >= MIN_CONTENT or 2 * len(text) >= len(whole)):
            return " ".join(parser.title.split()), text
    return " ".join(parser.title.split()), whole
