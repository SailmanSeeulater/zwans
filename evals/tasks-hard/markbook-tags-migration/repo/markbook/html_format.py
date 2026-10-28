"""The Netscape bookmark file format that every browser imports and exports.

    <!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
        <DT><H3>Dev</H3>
        <DL><p>
            <DT><A HREF="https://docs.python.org/3/" ADD_DATE="1700000000">Python docs</A>
        </DL><p>
    </DL><p>

Folders are <H3> headings, each followed by a <DL> list holding what is inside them.
ADD_DATE is seconds since 1970 (UTC); markbook keeps only the day.
"""

import html
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser

from .collection import Collection
from .model import Bookmark, normalize_folder

HEADER = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. It will be read and overwritten. -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
"""


def _timestamp(day: str) -> str:
    if not day:
        return ""
    moment = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
    return str(int(moment.timestamp()))


def _day(timestamp: str | None) -> str:
    if not timestamp or not timestamp.strip().isdigit():
        return ""
    return datetime.fromtimestamp(int(timestamp), tz=UTC).date().isoformat()


# ------------------------------------------------------------------------ export


@dataclass
class _Folder:
    bookmarks: list[Bookmark] = field(default_factory=list)
    children: dict[str, "_Folder"] = field(default_factory=dict)


def _tree(bookmarks: list[Bookmark]) -> _Folder:
    root = _Folder()
    for bookmark in bookmarks:
        node = root
        for name in bookmark.folder.split("/") if bookmark.folder else []:
            node = node.children.setdefault(name, _Folder())
        node.bookmarks.append(bookmark)
    return root


def _link(bookmark: Bookmark) -> str:
    attributes = f'HREF="{html.escape(bookmark.url)}"'
    if bookmark.added:
        attributes += f' ADD_DATE="{_timestamp(bookmark.added)}"'
    return f"<DT><A {attributes}>{html.escape(bookmark.title)}</A>"


def _write(node: _Folder, depth: int, out: list[str]) -> None:
    pad = "    " * depth
    out.append(f"{pad}<DL><p>")
    for bookmark in node.bookmarks:
        out.append(f"{pad}    {_link(bookmark)}")
    for name in sorted(node.children):
        out.append(f"{pad}    <DT><H3>{html.escape(name)}</H3>")
        _write(node.children[name], depth + 1, out)
    out.append(f"{pad}</DL><p>")


def export_html(collection: Collection) -> str:
    out: list[str] = []
    _write(_tree(list(collection)), 0, out)
    return HEADER + "\n".join(out) + "\n"


# ------------------------------------------------------------------------ import


@dataclass
class Imported:
    url: str
    title: str
    folder: str
    added: str


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[Imported] = []
        self._path: list[str] = []  # folder names of the <DL>s we are inside
        self._pending_folder: str | None = None  # an <H3> waiting for its <DL>
        self._open_dl: list[bool] = []  # per <DL>: did it open a folder?
        self._text: list[str] | None = None
        self._link: dict[str, str | None] | None = None
        self._in_h3 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h3":
            self._in_h3 = True
            self._text = []
        elif tag == "dl":
            opened = self._pending_folder is not None
            if opened:
                self._path.append(self._pending_folder)
                self._pending_folder = None
            self._open_dl.append(opened)
        elif tag == "a":
            self._link = {name.lower(): value for name, value in attrs}
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            self._pending_folder = "".join(self._text or []).strip()
            self._text = None
        elif tag == "dl" and self._open_dl:
            if self._open_dl.pop():
                self._path.pop()
        elif tag == "a" and self._link is not None:
            href = (self._link.get("href") or "").strip()
            title = " ".join("".join(self._text or []).split())
            if href:
                self.found.append(
                    Imported(
                        href,
                        title,
                        normalize_folder("/".join(self._path)),
                        _day(self._link.get("add_date")),
                    )
                )
            self._link = None
            self._text = None

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)


def parse_html(text: str) -> list[Imported]:
    parser = _Parser()
    parser.feed(text)
    parser.close()
    return parser.found


@dataclass
class ImportResult:
    added: list[Bookmark]
    skipped: list[str]  # URLs that were already there, or are not web pages


def import_html(collection: Collection, text: str) -> ImportResult:
    """Add every bookmark in a browser export that the collection does not have yet."""
    result = ImportResult([], [])
    for item in parse_html(text):
        try:
            result.added.append(collection.add(item.url, item.title, item.folder, added=item.added))
        except Exception:  # duplicate, or javascript:/place: links and the like
            result.skipped.append(item.url)
    return result
