# The markbook file format

A markbook file is one JSON object. Its `version` says which format it is in. markbook
reads every format it has ever written and always writes the current one.

## Format 4 (current)

```json
{
  "version": 4,
  "next_id": 4,
  "bookmarks": [
    {
      "id": 1,
      "url": "https://docs.python.org/3/",
      "title": "Python docs",
      "tags": ["dev", "python"],
      "added": "2024-05-01",
      "visits": 12,
      "starred": true
    }
  ]
}
```

| field     | type   | rules                                                              |
|-----------|--------|--------------------------------------------------------------------|
| `id`      | int    | unique, from 1 up to `next_id - 1`; never reused                    |
| `url`     | string | an http(s) URL                                                     |
| `title`   | string |                                                                    |
| `tags`    | list   | of normalised tags: lowercase, no spaces (words joined by `-`), not empty; no duplicates |
| `added`   | string | `YYYY-MM-DD`, or `""` when unknown                                 |
| `visits`  | int    | 0 or more                                                          |
| `starred` | bool   |                                                                    |

No other keys are allowed, at the top level or in a bookmark.

## History

- **Format 4** replaced `folder` with `tags`: a bookmark in folder `Dev/Python` got the
  tags `dev` and `python` (migration `m003_folders_to_tags`).
- **Format 3** added `starred` and `next_id` (migration `m002_stars_and_ids`).
- **Format 2** renamed `category` (`"Dev > Python"`) to `folder` (`"Dev/Python"`), and
  added `id` and `visits` (migration `m001_categories_to_folders`).
- **Format 1**: `{"version": 1, "bookmarks": [{"url", "title", "category", "added"}]}`.

## Changing the format

1. Bump `CURRENT_VERSION` in `markbook/schema.py` and update `validate()`.
2. Write the migration from the previous format in its own module in
   `markbook/migrations/`, and register it in `MIGRATIONS`.
3. Add a sample file in the old format to `tests/data/`, and describe the new format here.
