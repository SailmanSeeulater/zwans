"""The ``leafwiki`` command.

Every command works on the wiki in ``--dir`` (default: the ``LEAFWIKI_DIR`` environment
variable, else the current folder) and acts as ``--as`` (default: ``LEAFWIKI_USER``, else
your login name). Set ``LEAFWIKI_NOW`` to pin the clock. Exit status: 0 on success, 1 when
leafwiki refused (unknown page, name taken...), 2 for a bad command line.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .backup import create_backup, restore_backup
from .changes import describe
from .clock import env_clock
from .doctor import check
from .errors import WikiError
from .export import export_markdown, export_site
from .feeds import changes_feed, page_feed
from .importer import import_folder
from .settings import SCHEMA
from .sitemap import sitemap_xml
from .stats import format_stats, page_stats, wiki_stats
from .textutil import plural
from .wiki import Wiki

Handler = Callable[[Wiki, argparse.Namespace], int]
COMMANDS: dict[str, Handler] = {}


def command(name: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        COMMANDS[name] = handler
        return handler

    return register


def _default_user() -> str:
    try:
        return os.environ.get("LEAFWIKI_USER") or getpass.getuser()
    except Exception:  # no login name in some containers
        return "someone"


def _read_body(args: argparse.Namespace) -> str:
    if getattr(args, "text", None) is not None:
        return args.text.replace("\\n", "\n")
    if getattr(args, "file", None):
        if args.file == "-":
            return sys.stdin.read()
        return Path(args.file).read_text("utf-8")
    raise WikiError("give the text with --text or --file")


def _emit(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


# -- pages ---------------------------------------------------------------------------------


@command("new")
def cmd_new(wiki: Wiki, args: argparse.Namespace) -> int:
    page = wiki.create_page(args.title, _read_body(args), args.user, args.summary or "", args.tag)
    print(f"created {page.title}")
    return 0


@command("edit")
def cmd_edit(wiki: Wiki, args: argparse.Namespace) -> int:
    before = wiki.page(args.title)
    page = wiki.edit_page(args.title, _read_body(args), args.user, args.summary or "")
    if page.current.number == before.current.number:
        print(f"{page.title} is unchanged")
    else:
        print(f"{page.title} is now at revision {page.current.number}")
    return 0


@command("show")
def cmd_show(wiki: Wiki, args: argparse.Namespace) -> int:
    page = wiki.page(args.title)
    if args.html:
        _emit(wiki.render(page.title))
        return 0
    revision = wiki.revision(page.title, args.rev) if args.rev else page.current
    print(f"# {page.title}")
    if page.tags:
        print(f"tags: {', '.join(page.tags)}")
    print(f"revision {revision.number}, {revision.at} by {revision.author or '-'}")
    print()
    _emit(revision.body)
    return 0


@command("history")
def cmd_history(wiki: Wiki, args: argparse.Namespace) -> int:
    for revision in reversed(wiki.history(args.title)):
        print(f"{revision.number:>4}  {revision.at}  {revision.author or '-':<12} {revision.summary}")
    return 0


@command("diff")
def cmd_diff(wiki: Wiki, args: argparse.Namespace) -> int:
    _emit(wiki.diff(args.title, args.old, args.new) or "(no differences)")
    return 0


@command("revert")
def cmd_revert(wiki: Wiki, args: argparse.Namespace) -> int:
    page = wiki.revert(args.title, args.number, args.user)
    print(f"{page.title} is now at revision {page.current.number}")
    return 0


@command("rename")
def cmd_rename(wiki: Wiki, args: argparse.Namespace) -> int:
    page = wiki.rename_page(args.title, args.new_title, args.user)
    print(f"renamed to {page.title}")
    return 0


@command("delete")
def cmd_delete(wiki: Wiki, args: argparse.Namespace) -> int:
    title = wiki.page(args.title).title
    wiki.delete_page(title, args.user)
    print(f"deleted {title}")
    return 0


@command("trash")
def cmd_trash(wiki: Wiki, args: argparse.Namespace) -> int:
    for entry in wiki.trash():
        print(f"{entry.id}  {entry.title}  {entry.deleted_at}  {entry.deleted_by or '-'}")
    return 0


@command("restore")
def cmd_restore(wiki: Wiki, args: argparse.Namespace) -> int:
    page = wiki.restore_page(args.entry, args.user, title=args.title)
    print(f"restored {page.title}")
    return 0


@command("purge")
def cmd_purge(wiki: Wiki, args: argparse.Namespace) -> int:
    entry = wiki.purge_page(args.entry, args.user)
    print(f"purged {entry.title}")
    return 0


@command("list")
def cmd_list(wiki: Wiki, args: argparse.Namespace) -> int:
    titles = wiki.pages_tagged(args.tag) if args.tag else wiki.titles()
    for title in titles:
        print(title)
    return 0


@command("search")
def cmd_search(wiki: Wiki, args: argparse.Namespace) -> int:
    hits = wiki.search(" ".join(args.query), limit=args.limit)
    if not hits:
        print("no matches")
        return 0
    for hit in hits:
        print(f"{hit.title}\n    {hit.snippet}")
    return 0


@command("reindex")
def cmd_reindex(wiki: Wiki, args: argparse.Namespace) -> int:
    print(f"indexed {plural(wiki.rebuild_index(), 'page')}")
    return 0


# -- tags and links ------------------------------------------------------------------------


@command("tag")
def cmd_tag(wiki: Wiki, args: argparse.Namespace) -> int:
    if not args.changes:
        raise WikiError("say which tags to add (+tag) or remove (-tag)")
    add = [t[1:] if t.startswith("+") else t for t in args.changes if not t.startswith("-")]
    remove = [t[1:] for t in args.changes if t.startswith("-")]
    page = wiki.page(args.title)
    tags = [t for t in [*page.tags, *add] if t not in remove]
    page = wiki.set_tags(page.title, tags, args.user)
    print(f"{page.title}: {', '.join(page.tags) or '(no tags)'}")
    return 0


@command("tags")
def cmd_tags(wiki: Wiki, args: argparse.Namespace) -> int:
    for tag, count in wiki.tags().items():
        print(f"{tag} ({count})")
    return 0


@command("links")
def cmd_links(wiki: Wiki, args: argparse.Namespace) -> int:
    page = wiki.page(args.title)
    print("links to:")
    for link in wiki.links(page.title):
        print(f"  {link.target}" + ("" if link.exists else " (missing)"))
    print("linked from:")
    for title in wiki.backlinks(page.title):
        print(f"  {title}")
    return 0


# -- attachments and comments ----------------------------------------------------------------


@command("attach")
def cmd_attach(wiki: Wiki, args: argparse.Namespace) -> int:
    path = Path(args.file)
    attachment = wiki.attach(args.title, args.name or path.name, path.read_bytes(), args.user)
    print(f"attached {attachment.name} ({attachment.size} bytes)")
    return 0


@command("detach")
def cmd_detach(wiki: Wiki, args: argparse.Namespace) -> int:
    wiki.detach(args.title, args.name, args.user)
    print(f"removed {args.name}")
    return 0


@command("comment")
def cmd_comment(wiki: Wiki, args: argparse.Namespace) -> int:
    comment = wiki.comment(args.title, args.text, args.user, reply_to=args.reply_to)
    print(f"added {comment.id}")
    return 0


@command("comments")
def cmd_comments(wiki: Wiki, args: argparse.Namespace) -> int:
    def show(threads, depth: int) -> None:
        for thread in threads:
            c = thread.comment
            print(f"{'  ' * depth}[{c.id}] {c.author or '-'} {c.at}: {c.text}")
            show(thread.replies, depth + 1)

    show(wiki.comment_threads(args.title), 0)
    return 0


# -- watching ------------------------------------------------------------------------------------


@command("watch")
def cmd_watch(wiki: Wiki, args: argparse.Namespace) -> int:
    new = wiki.watch(args.title, args.user)
    print(("watching " if new else "already watching ") + wiki.page(args.title).title)
    return 0


@command("unwatch")
def cmd_unwatch(wiki: Wiki, args: argparse.Namespace) -> int:
    wiki.unwatch(args.title, args.user)
    print(f"stopped watching {wiki.page(args.title).title}")
    return 0


@command("watching")
def cmd_watching(wiki: Wiki, args: argparse.Namespace) -> int:
    for title in wiki.watched_by(args.user):
        print(title)
    return 0


@command("outbox")
def cmd_outbox(wiki: Wiki, args: argparse.Namespace) -> int:
    messages = wiki.drain_outbox() if args.drain else wiki.outbox()
    for m in messages:
        print(json.dumps(m.to_dict(), ensure_ascii=False))
    return 0


# -- reports and exports -----------------------------------------------------------------------


@command("changes")
def cmd_changes(wiki: Wiki, args: argparse.Namespace) -> int:
    for change in wiki.recent_changes(args.limit):
        print(describe(change))
    return 0


@command("feed")
def cmd_feed(wiki: Wiki, args: argparse.Namespace) -> int:
    _emit(page_feed(wiki, args.page) if args.page else changes_feed(wiki, args.limit))
    return 0


@command("sitemap")
def cmd_sitemap(wiki: Wiki, args: argparse.Namespace) -> int:
    _emit(sitemap_xml(wiki))
    return 0


@command("stats")
def cmd_stats(wiki: Wiki, args: argparse.Namespace) -> int:
    stats = page_stats(wiki, args.page) if args.page else wiki_stats(wiki)
    _emit(json.dumps(stats, indent=2, ensure_ascii=False) if args.json else format_stats(stats))
    return 0


@command("export")
def cmd_export(wiki: Wiki, args: argparse.Namespace) -> int:
    if args.markdown:
        written = export_markdown(wiki, args.folder)
    else:
        written = export_site(wiki, args.folder)
    print(f"wrote {plural(len(written), 'file')} to {args.folder}")
    return 0


@command("import")
def cmd_import(wiki: Wiki, args: argparse.Namespace) -> int:
    result = import_folder(wiki, args.folder, args.user)
    print(result.summary())
    for name, problem in result.failed:
        print(f"  {name}: {problem}", file=sys.stderr)
    return 1 if result.failed else 0


# -- housekeeping --------------------------------------------------------------------------------


@command("maintain")
def cmd_maintain(wiki: Wiki, args: argparse.Namespace) -> int:
    for line in wiki.maintain().lines():
        print(line)
    return 0


@command("check")
def cmd_check(wiki: Wiki, args: argparse.Namespace) -> int:
    problems = check(wiki)
    for problem in problems:
        print(problem)
    if not problems:
        print("no problems found")
    return 1 if problems else 0


@command("config")
def cmd_config(wiki: Wiki, args: argparse.Namespace) -> int:
    if args.key is None:
        for key, value in wiki.settings.items():
            print(f"{key} = {value}")
        return 0
    if args.reset:
        wiki.reset_setting(args.key)
    elif args.value is not None:
        wiki.set_setting(args.key, args.value)
    print(f"{args.key} = {wiki.settings.get(args.key)}")
    return 0


@command("backup")
def cmd_backup(wiki: Wiki, args: argparse.Namespace) -> int:
    counts = create_backup(wiki, args.file)
    print(f"backed up {plural(counts['pages'], 'page')} to {args.file}")
    return 0


# -- parsing -------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="leafwiki", description="A small wiki in a folder.")
    parser.add_argument("--dir", default=os.environ.get("LEAFWIKI_DIR", "."), help="the wiki folder")
    parser.add_argument("--as", dest="user", default=None, help="who is acting")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a wiki")
    init.add_argument("--name")
    init.add_argument("--base-url")

    def body_args(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group()
        group.add_argument("--text")
        group.add_argument("--file")
        p.add_argument("--summary")

    p = sub.add_parser("new", help="create a page")
    p.add_argument("title")
    body_args(p)
    p.add_argument("--tag", action="append", default=[])

    p = sub.add_parser("edit", help="save a new revision of a page")
    p.add_argument("title")
    body_args(p)

    p = sub.add_parser("show", help="print a page")
    p.add_argument("title")
    p.add_argument("--rev", type=int)
    p.add_argument("--html", action="store_true")

    p = sub.add_parser("history", help="list a page's revisions")
    p.add_argument("title")

    p = sub.add_parser("diff", help="compare two revisions")
    p.add_argument("title")
    p.add_argument("old", type=int)
    p.add_argument("new", type=int)

    p = sub.add_parser("revert", help="bring back an old revision")
    p.add_argument("title")
    p.add_argument("number", type=int)

    p = sub.add_parser("rename", help="rename a page")
    p.add_argument("title")
    p.add_argument("new_title")

    p = sub.add_parser("delete", help="delete a page")
    p.add_argument("title")

    sub.add_parser("trash", help="list deleted pages")

    p = sub.add_parser("restore", help="bring a page back from the trash")
    p.add_argument("entry")
    p.add_argument("--title")

    p = sub.add_parser("purge", help="delete a page in the trash for good")
    p.add_argument("entry")

    p = sub.add_parser("list", help="list pages")
    p.add_argument("--tag")

    p = sub.add_parser("search", help="full-text search")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=20)

    sub.add_parser("reindex", help="rebuild the search index")

    p = sub.add_parser("tag", help="change a page's tags: +add -remove")
    p.add_argument("title")
    p.add_argument("changes", nargs=argparse.REMAINDER, metavar="+TAG|-TAG")

    sub.add_parser("tags", help="list tags")

    p = sub.add_parser("links", help="a page's links and backlinks")
    p.add_argument("title")

    p = sub.add_parser("attach", help="attach a file to a page")
    p.add_argument("title")
    p.add_argument("file")
    p.add_argument("--name")

    p = sub.add_parser("detach", help="remove an attachment")
    p.add_argument("title")
    p.add_argument("name")

    p = sub.add_parser("comment", help="comment on a page")
    p.add_argument("title")
    p.add_argument("text")
    p.add_argument("--reply-to")

    p = sub.add_parser("comments", help="show a page's comments")
    p.add_argument("title")

    for name in ("watch", "unwatch"):
        p = sub.add_parser(name, help=f"{name} a page")
        p.add_argument("title")
    sub.add_parser("watching", help="pages you watch")

    p = sub.add_parser("outbox", help="print waiting notifications")
    p.add_argument("--drain", action="store_true")

    p = sub.add_parser("changes", help="recent changes")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("feed", help="print the RSS feed")
    p.add_argument("--limit", type=int)
    p.add_argument("--page")

    sub.add_parser("sitemap", help="print sitemap.xml")

    p = sub.add_parser("stats", help="statistics")
    p.add_argument("--page")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("export", help="export the site")
    p.add_argument("folder")
    p.add_argument("--markdown", action="store_true")

    p = sub.add_parser("import", help="import a folder of text files")
    p.add_argument("folder")

    sub.add_parser("maintain", help="run the maintenance job")
    sub.add_parser("check", help="look for damage in the wiki's folder")

    p = sub.add_parser("config", help="show or change settings")
    p.add_argument("key", nargs="?", choices=sorted(SCHEMA), metavar="KEY")
    p.add_argument("value", nargs="?")
    p.add_argument("--reset", action="store_true")

    p = sub.add_parser("backup", help="write a backup zip")
    p.add_argument("file")

    p = sub.add_parser("unpack-backup", help="restore a backup into a new folder")
    p.add_argument("file")
    p.add_argument("folder")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:  # argparse has printed the problem already
        return int(stop.code or 0)
    args.user = args.user or _default_user()
    clock = env_clock()
    try:
        if args.command == "init":
            Wiki.init(args.dir, clock=clock, site_name=args.name, base_url=args.base_url)
            print(f"created a wiki in {args.dir}")
            return 0
        if args.command == "unpack-backup":
            wiki = restore_backup(args.file, args.folder, clock=clock)
            print(f"restored {plural(len(wiki.titles()), 'page')} into {args.folder}")
            return 0
        wiki = Wiki.open(args.dir, clock=clock)
        return COMMANDS[args.command](wiki, args)
    except WikiError as error:
        print(f"leafwiki: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"leafwiki: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
