# feedsvc

The feed service behind the mobile app: people publish short posts, follow
each other, and scroll through the posts of the people they follow.

## Feeds

- **Home feed** (`GET /feed?user=ada`): posts by everyone `ada` follows, plus
  her own, minus authors she muted.
- **Profile** (`GET /users/ada/posts`): `ada`'s own posts.

Both are ordered newest first. Timestamps are kept to the second, so posts can
share a timestamp (a busy author, or posts brought in by the blog importer);
posts with the same timestamp are ordered by id, highest (most recently added)
first.

## Paging

A response has at most `limit` posts (default 20, at most 100) and, if there
are more, a `next` cursor. Pass it back as `cursor` to get the following page.
Cursors are opaque strings; clients must not build or parse them.

Walking a feed page by page returns every post exactly once, in feed order,
even while new posts are being published: new posts don't push older ones onto
the next page and don't show up twice; they appear at the top, where
`/feed/refresh` finds them.

`GET /feed/refresh?user=ada&since=<cursor>` returns the posts added to the
top of the home feed since the page the `since` cursor came from (the `top`
cursor of a first page, or of an earlier refresh), newest first, with a new
`top` cursor.

The old `page=N` parameter (offset paging) is deprecated: it shows duplicates
and gaps whenever posts are published during a scroll.

## Storage

`backend = "sqlite"` (the default, used in production) keeps everything in a
SQLite file; `backend = "memory"` is for tests and demos. Both must behave the
same.

## Importing an old blog

`python -m feedsvc.importer export.json --author ada` imports posts from the
old blog's JSON export. The old blog only kept dates, so imported posts are
timestamped at midnight UTC on their day.

## Development

```
python -m pytest
```
