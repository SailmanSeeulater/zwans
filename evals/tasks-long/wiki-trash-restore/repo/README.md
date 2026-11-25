# leafwiki

A small wiki that lives in a folder of JSON files. Pages have full revision history,
tags, attachments and comments; people can watch pages and get notified; there is
full-text search, a recent-changes feed, a static HTML export, statistics, backups and a
maintenance job to run from cron. Python 3.12, standard library only.

```bash
leafwiki --dir ~/notes init --name "Kitchen Notes" --base-url https://notes.example
leafwiki --dir ~/notes new "Kettle" --text "Descale with vinegar. See [[Teapot]]." --tag kitchen
leafwiki --dir ~/notes search vinegar
leafwiki --dir ~/notes export ~/public_html/notes
```

From Python:

```python
from leafwiki import Wiki

wiki = Wiki.open("notes")            # Wiki.init(...) creates one, Wiki.memory() keeps it in RAM
wiki.create_page("Kettle", "Descale with vinegar.", author="ana", tags=["kitchen"])
wiki.edit_page("Kettle", "Descale with citric acid.", author="bo", summary="gentler")
[hit.title for hit in wiki.search("citric")]   # ["Kettle"]
```

## Pages

A page has an id (`p1`, `p2`, ... never reused), a title, tags, attachments and a list
of revisions. Every edit adds a revision (number, time, author, summary, full text);
saving the same text again adds nothing. `revert(title, n)` brings back revision *n* as a
new revision, and `diff(title, a, b)` compares two.

Titles are matched by their **slug**: lower case, spaces turned into dashes ("Front Page"
→ `front-page`). Two titles with the same slug are the same page, so `wiki.page("front
page")` finds "Front Page", and creating "FRONT PAGE" next to it raises `PageExists`.
Titles can't be empty, contain `[ ] | # < > { } / \`, start with a dot, or be longer
than 120 characters (`InvalidTitle`).

Renaming keeps the page's id and history; the old title is free again afterwards. Links
in other pages are not rewritten.

`delete_page(title)` removes a page with its revisions, tags, comments and watchers.
Asking for a page that doesn't exist raises `PageNotFound` (that goes for every call that
takes a title).

All timestamps are UTC strings like `2026-03-01T09:00:00Z`. The wiki reads the time from
the clock it is given (`Wiki.memory(clock=...)`), the CLI from `LEAFWIKI_NOW` if set.

## Markup

A small Markdown-like language: `#`/`##`/`###` headings, blank-line paragraphs, `-` and
`1.` lists, `>` quotes, fenced code blocks, `----` rules, `**strong**`, `*emphasis*`,
`` `code` `` and `[text](https://...)` web links. Page links are written `[[Title]]` or
`[[Title|shown text]]`. Links inside code don't count.

When a page is rendered (`wiki.render(title)`, the export) a link to a page that exists
becomes `<a class="wikilink" href="...">`; a link to a page that doesn't exist gets the
class `wikilink missing` so it can be shown in red.

## Links, backlinks, tags

* `wiki.links(title)`: what a page links to, each with whether the target exists.
* `wiki.backlinks(title)`: titles of the other pages whose current text links to it
  (the target needn't exist). Shown as "Linked from" in the export.
* `wiki.wanted()`: pages that are linked to but don't exist; `wiki.orphans()`: pages
  nothing links to.
* Tags are lower case without spaces (`"Tea Time"` → `tea-time`). `wiki.tags()` gives
  every tag in use with how many pages carry it; `wiki.pages_tagged(tag)` the titles.

## Attachments and comments

`attach(title, name, data)` stores a file with a page (replacing one of the same name);
`attachment(title, name)` reads it back, `detach` removes it. Contents are stored by
hash, so the same file attached to two pages is kept once. The size limit is the
`max_attachment_bytes` setting.

`comment(title, text, author, reply_to=None)` adds a comment (ids `c1`, `c2`, ...),
`comments(title)` lists a page's comments oldest first, `comment_threads(title)` nests
replies, `edit_comment` and `delete_comment` (which removes the replies too) work by id.
`recent_comments()` lists the latest comments across the wiki as `(page title, comment)`.

## Watching and the outbox

`watch(title, user)` / `unwatch` / `watchers(title)` / `watched_by(user)`. When something
happens to a watched page, every watcher except the person who did it gets a message in
the **outbox**: `{"to", "event", "page", "by", "at"}` where `event` is one of `edited`
(edits and reverts), `renamed`, `deleted`, `commented`, `attached`. leafwiki doesn't send
mail; a delivery job reads `wiki.outbox()` (or `leafwiki outbox --drain`) and drains it.

## Recent changes and feeds

Every change is logged: `wiki.recent_changes(limit=50, kinds=None)` returns entries
newest first, each with `seq`, `at`, `kind`, `page_id`, `title`, `author`, `summary`.
Kinds: `create`, `edit`, `revert`, `rename` (summary "Old → New"), `delete`, `tag`
(summary like "+new -old"), `attach`, `detach`, `comment`.

`leafwiki.feeds.changes_feed(wiki)` renders the recent changes as RSS 2.0, newest first
(`feed_items` of them). Each item's title is "Title: kind", its `<category>` the kind, and
its `<link>` points at the page in the exported site under its current title
(`<base_url>/pages/<slug>.html`). `page_feed(wiki, title)` lists one page's revisions.

## Search

`wiki.search(query)` returns hits (`title`, `score`, `snippet`), best first. Words must all
match (in the title, the text or the tags); matching ignores case and simple word
endings. Query syntax:

| query            | finds                                     |
|------------------|-------------------------------------------|
| `kettle descale` | pages containing both words               |
| `"hard water"`   | the exact phrase                          |
| `-limescale`     | leaves out pages with the word            |
| `tag:kitchen`    | pages with that tag (`-tag:` to exclude)  |
| `title:kettle`   | the word must be in the title             |

The index is kept up to date as pages change and saved in the wiki's folder, so opening a
big wiki doesn't re-index it. When the saved index is missing or out of date it is rebuilt
from the pages on open; `wiki.rebuild_index()` (`leafwiki reindex`) rebuilds it on demand.

## Storage

A wiki is a folder:

```
wiki.json            manifest: {"format": 2, "settings": ..., counters, index generation}
pages/<id>.json      a page with all its revisions and attachment records
blobs/..             attachment contents, by hash
comments/<id>.json   a page's comments
watchers.json        page id -> watchers
changes.json         the recent-changes log
outbox.json          notifications waiting to go out
index.json           the saved search index
```

Only `wiki.json`'s `format` is meant to be read by other tools; the rest may change
between releases. Files are replaced atomically.

**leafwiki 1.x** wikis (format 1: everything in `wiki.json`) are upgraded on open. 1.x
never really deleted anything: a deleted page was kept with `"deleted": true`. The
upgrade drops those pages and their comments.

## Reports and exports

* **Statistics**: `leafwiki.stats.wiki_stats(wiki)` (`leafwiki stats --json`) returns
  `pages`, `revisions` (total), `words` (in the current texts), `attachments`,
  `attachment_bytes`, `comments`, `tags` (distinct tags), `authors` (distinct revision
  authors), `top_linked` (up to five `[title, pages linking to it]`, most first),
  `orphans` (pages no other page links to) and `wanted` (link targets with no page, as
  written in the first link). `page_stats(wiki, title)` gives the same for one page.
* **Sitemap**: `leafwiki.sitemap.sitemap_xml(wiki)` lists every page's address with its
  last change date, the front page first.
* **Static export**: `leafwiki.export.export_site(wiki, folder)` (`leafwiki export`)
  writes `index.html`, `pages/<slug>.html` for every page (body, tags, attachments,
  "Linked from"), `files/<slug>/<name>` for attachments, `tags/index.html` and
  `tags/<tag>.html`, `recent.html`, `sitemap.xml` and `style.css`.
* **Markdown export**: `export_markdown(wiki, folder)` writes `<slug>.md` per page with a
  small front matter; `leafwiki.importer.import_folder(wiki, folder)` reads such a folder
  (or any folder of `.md`/`.txt` files) back in.

## Maintenance and settings

Run `leafwiki maintain` (`wiki.maintain()`) daily. It returns a report with
`revisions_pruned`, `changes_trimmed`, `outbox_dropped` and `blobs_removed`:

* keeps only the last `keep_revisions` revisions of each page (0, the default, keeps all),
* drops recent-changes entries older than `changes_retention_days`,
* caps the outbox at `outbox_limit` messages, dropping the oldest,
* removes attachment contents no page uses any more (detaching or deleting leaves them
  for maintenance to clean up).

Settings live in `wiki.json`; `leafwiki config KEY VALUE` changes one, `wiki.set_setting`
from Python. Unknown keys and bad values are refused (`InvalidSetting`).

| setting                  | default                  |                                         |
|--------------------------|--------------------------|-----------------------------------------|
| `site_name`              | `My Wiki`                | page titles, feeds, the export          |
| `base_url`               | `http://localhost/wiki`  | where the export is published           |
| `front_page`             | `Front Page`             | listed first in the export and sitemap  |
| `keep_revisions`         | `0`                      | see maintenance                         |
| `changes_retention_days` | `90`                     | see maintenance                         |
| `outbox_limit`           | `1000`                   | see maintenance                         |
| `max_attachment_bytes`   | `5000000`                | largest attachment                      |
| `feed_items`             | `30`                     | items in the changes feed               |

## Backups and checks

`leafwiki.backup.create_backup(wiki, "notes.zip")` writes the whole wiki (every record and
attachment) to one zip; `restore_backup("notes.zip", "new-folder")` (`leafwiki
unpack-backup`) unpacks it into a new folder and opens it. The search index is rebuilt.

`leafwiki.doctor.check(wiki)` (`leafwiki check`) looks for damage: attachments without
contents, comments or watchers kept for pages that don't exist, a search index that
doesn't match the pages. A wiki only ever changed through leafwiki reports nothing.

## Command line

```
leafwiki [--dir FOLDER] [--as USER] COMMAND ...

init [--name N] [--base-url U]       new TITLE (--text T | --file F) [--tag T]... [--summary S]
edit TITLE (--text T | --file F)     show TITLE [--rev N] [--html]
history TITLE    diff TITLE A B      revert TITLE N      rename TITLE NEW      delete TITLE
list [--tag T]   search WORDS...     reindex             tag TITLE +a -b ...   tags
links TITLE      attach TITLE FILE [--name N]            detach TITLE NAME
comment TITLE TEXT [--reply-to ID]   comments TITLE      watch / unwatch TITLE   watching
outbox [--drain] changes [--limit N] feed [--page TITLE] sitemap   stats [--page T] [--json]
export FOLDER [--markdown]           import FOLDER       maintain   check
config [KEY [VALUE] [--reset]]       backup FILE         unpack-backup FILE FOLDER
```

`--dir` defaults to `LEAFWIKI_DIR`, else the current folder; `--as` to `LEAFWIKI_USER`,
else your login. Exit status 0 on success, 1 when leafwiki refuses (the reason goes to
stderr), 2 for a bad command line.

## The trash (agreed, not built yet)

People delete the wrong page and there's no way back. Instead of deleting outright,
deleting moves a page to a **trash** it can be restored from. This is what we agreed:

**Deleting.** `wiki.delete_page(title, author="")` moves the page to the trash and returns
the id of its trash entry (a string). Everything that belongs to the page goes with it:
revisions, tags, attachments (with their contents), comments and watchers. Deleting still
logs a `delete` change and still sends watchers `deleted`, as today.

**Listing.** `wiki.trash()` returns the entries, most recently deleted first. An entry has
`id`, `title` (the page's title when it was deleted), `deleted_at` (a timestamp like all
the others) and `deleted_by`. Unknown entry ids raise `TrashEntryNotFound`, a new error in
`leafwiki.errors` that is both a `WikiError` and a `LookupError`.

**Restoring.** `wiki.restore_page(entry_id, author="", title=None)` puts the page back
exactly as it was and returns it: the same page id, the same revisions (numbers, times,
authors, summaries, text), tags, attachments and their contents, comments (ids, replies,
edits) and watchers. Restoring isn't an edit: it adds no revision. It logs a `restore`
change and sends the page's watchers `restored`. If a page with the same slug exists by
then, restoring raises `PageExists`, unless `title=` is given, in which case the page comes
back under that title (and only the title differs).

**Purging.** `wiki.purge_page(entry_id, author="")` deletes the entry for good. It logs a
`purge` change and sends the page's watchers `purged`. Afterwards nothing of the page may
be left in the wiki's folder: no file may still contain its text, its comments or its
attachments' contents, the search index included. (Attachment contents also used by another
page, live or in the trash, stay, of course. The recent-changes log is the one exception:
its entries about the page stay as they were.)

**Retention.** A new setting, `trash_retention_days` (default `30`, at least `1`). The
maintenance job purges every entry that has been in the trash for more than that many
days (exactly 30 days is not more than 30), sending `purged` and logging `purge` with
`maintenance` as the author, and reports how many it purged as `trash_purged`. Apart from
that, maintenance leaves the trash alone: `keep_revisions` doesn't prune pages in the
trash, and their attachment contents count as used.

**Out of sight everywhere.** While a page is in the trash it doesn't exist for the rest of
leafwiki: every call that takes a title raises `PageNotFound` for it, and it is left out of
`pages()` and `titles()`, search (live, after reopening the wiki, and after
`rebuild_index()`), `tags()` and `pages_tagged()`, other pages' backlinks (its own links
don't count while it's in the trash), `watched_by()`, `recent_comments()`, every figure in
the statistics, the sitemap, the static export and the Markdown export. Links to it are
missing links (class `missing`, listed as wanted). Its title is free: another page can be
created with it or renamed to it. After a restore it is back in all of these.

**Feeds.** Feed items about a page that isn't there (in the trash, or purged) have no
`<link>`; once a page is restored its items link to it again.

**Statistics** gain `trashed`: the number of entries in the trash.

**Everything else.** The trash survives reopening the wiki and is part of backups
(restoring a backup brings the trash back, and its entries can be restored from there).
`check` reports no problems for pages in the trash. Upgrading a 1.x wiki puts the pages
flagged `"deleted": true` in the trash, with their comments, instead of dropping them; their
entries are `deleted_by` `upgrade` at the time of the upgrade.

**Command line.** `delete` keeps its output. New commands: `trash` prints one line per
entry, `ID  TITLE  DELETED_AT  DELETED_BY` (two spaces between fields), newest first;
`restore ID [--title TITLE]` prints `restored TITLE`; `purge ID` prints `purged TITLE`.
An unknown id is an error (exit status 1). `config trash_retention_days N` sets the
retention, and `maintain` prints the new `trash_purged` line along with the others.
