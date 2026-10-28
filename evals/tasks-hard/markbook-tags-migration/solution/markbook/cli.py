"""The markbook command line.

    markbook [--file PATH] <command> ...

The file defaults to $MARKBOOK_FILE, or bookmarks.json. MARKBOOK_TODAY (YYYY-MM-DD) fixes
the date new bookmarks get, for scripts and tests.
"""

import argparse
import os
import sys
from pathlib import Path

from . import store
from .collection import Collection
from .html_format import export_html, import_html
from .migrations import MigrationError
from .model import Bookmark, MarkbookError
from .schema import CURRENT_VERSION, SchemaError


def _line(bookmark: Bookmark) -> str:
    star = "*" if bookmark.starred else " "
    line = f"{bookmark.id:>4} {star} {bookmark.title}  <{bookmark.url}>"
    if bookmark.tags:
        line += f"  [{', '.join(bookmark.tags)}]"
    return line


def _today() -> str | None:
    return os.environ.get("MARKBOOK_TODAY") or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="markbook", description="Bookmarks in a JSON file.")
    parser.add_argument(
        "--file", type=Path, default=Path(os.environ.get("MARKBOOK_FILE", "bookmarks.json"))
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("add", help="bookmark a URL")
    p.add_argument("url")
    p.add_argument("--title", default="")
    p.add_argument("--tag", action="append", default=[], help="tag it (repeat for more tags)")
    p.add_argument("--star", action="store_true")

    p = sub.add_parser("list", help="list bookmarks")
    p.add_argument("--tag", help="only bookmarks with this tag")
    p.add_argument("--starred", action="store_true")

    p = sub.add_parser("find", help="search titles, URLs and tags")
    p.add_argument("text")

    for name, text in (("tag", "add tags to a bookmark"), ("untag", "take tags off a bookmark")):
        p = sub.add_parser(name, help=text)
        p.add_argument("id", type=int)
        p.add_argument("tags", nargs="+")

    for name in ("star", "unstar", "visit", "rm"):
        sub.add_parser(name).add_argument("id", type=int)

    sub.add_parser("tags", help="tags in use, with how many bookmarks have each")

    sub.add_parser(
        "export", help="write every bookmark as a browser bookmark file (HTML) to stdout"
    )
    p = sub.add_parser("import", help="add the bookmarks from a browser bookmark file (HTML)")
    p.add_argument("source", type=Path)

    sub.add_parser("check", help="check the file is valid")
    sub.add_parser("upgrade", help="rewrite the file in the current format, keeping a backup")
    return parser


def run(args: argparse.Namespace) -> int:
    path: Path = args.file
    collection: Collection = store.load(path)
    changed = False

    match args.command:
        case "add":
            bookmark = collection.add(
                args.url, args.title, args.tag, starred=args.star, added=_today()
            )
            print(f"added {bookmark.id}")
            changed = True
        case "list":
            bookmarks = collection.tagged(args.tag) if args.tag is not None else list(collection)
            for bookmark in bookmarks:
                if bookmark.starred or not args.starred:
                    print(_line(bookmark))
        case "find":
            for bookmark in collection.find(args.text):
                print(_line(bookmark))
        case "tag":
            collection.tag(args.id, *args.tags)
            changed = True
        case "untag":
            collection.untag(args.id, *args.tags)
            changed = True
        case "star" | "unstar":
            collection.star(args.id, args.command == "star")
            changed = True
        case "visit":
            print(collection.visit(args.id).url)
            changed = True
        case "rm":
            collection.remove(args.id)
            changed = True
        case "tags":
            for tag, count in collection.tags().items():
                print(f"{tag}  {count}")
        case "export":
            sys.stdout.write(export_html(collection))
        case "import":
            result = import_html(collection, args.source.read_text(encoding="utf-8"))
            print(f"imported {len(result.added)}, skipped {len(result.skipped)}")
            changed = True
        case "check":
            print(f"ok: {len(collection)} bookmarks (format {CURRENT_VERSION})")
        case "upgrade":
            old = collection.loaded_version
            if old is None or old == CURRENT_VERSION:
                print(f"already at format {CURRENT_VERSION}")
            else:
                store.save(collection, path)
                print(
                    f"upgraded from format {old} to {CURRENT_VERSION} (backup: {store.backup_path(path, old).name})"
                )

    if changed:
        store.save(collection, path)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (MarkbookError, SchemaError, MigrationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
