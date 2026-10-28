# sitegen

A small static-site generator for blogs. Write posts in a Markdown subset, run
`sitegen build`, and upload the `public/` folder.

## Layout of a site

```
mysite/
    site.toml            settings (see below)
    content/
        about.md         a stand-alone page, published at /about/
        posts/
            hello.md     a post, published at /posts/<slug>/
    templates/           optional; overrides the built-in theme, file by file
    static/              optional; copied to public/static/ as is
```

## Posts

A post starts with front matter between two `---` lines:

```
---
title: Shipping sitegen 1.0
date: 2026-03-14
tags: [python, releases]
summary: Optional. Shown on listings instead of the first paragraph.
draft: false
---
The first paragraph is the post's excerpt on listings, unless `summary` is set.

The rest of the post only appears on the post's own page.
```

`slug` may be given in the front matter; otherwise it is made from the title.
Drafts are left out unless you build with `--drafts`.

## What gets built

| Output                          | What it shows                                          |
|---------------------------------|--------------------------------------------------------|
| `index.html`, `page/N/`         | the newest posts, `posts_per_page` at a time            |
| `posts/<slug>/`                 | one post                                               |
| `<page>/`                       | one stand-alone page                                   |
| `archive/`                      | every post, newest first, grouped by year              |
| `tags/`                         | every tag with its number of posts                     |
| `tags/<tag>/`                   | the posts with that tag, newest first                  |
| `feed.xml`                      | Atom feed of the newest `feed_size` posts              |
| `sitemap.xml`                   | every page                                             |

The home page and the tag pages show each post's title, date, tags, reading
time and excerpt; the feed shows the same without the reading time, and the
archive shows titles and dates.

## Incremental builds

`sitegen build` remembers what it built last time (in `public/.sitegen-cache.json`)
and only re-renders and rewrites the outputs whose inputs changed, so a
one-line fix to one post doesn't rewrite the whole site and your upload tool
only sends what changed. The build report lists the files it wrote.

For example, fixing a typo in the third paragraph of a post rewrites only that
post's page: listings don't show the third paragraph. Changing a post's title,
on the other hand, also rewrites every listing the post appears on.

`sitegen build --clean` deletes `public/` first and builds everything.

## Serving locally

`sitegen serve` builds the site, serves `public/` on http://localhost:8000/ and
watches the site folder: whenever a file changes it runs an incremental build
again (in the same process), so you can keep a browser open while you write.

## site.toml

```toml
title = "My blog"
base_url = "https://example.org/"
author = "Ada"
posts_per_page = 5      # home page and page/N/
feed_size = 10
date_format = "%d %b %Y"
```

## Development

```
python -m pytest
```
