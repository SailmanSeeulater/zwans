# markbook

Bookmarks in a JSON file, from the command line.

```
python -m markbook add https://docs.python.org/3/ --title "Python docs" --folder Dev/Python --star
python -m markbook list --folder Dev
python -m markbook find python
python -m markbook export > bookmarks.html      # for any browser
python -m markbook import firefox-export.html
```

The file is `bookmarks.json` unless `--file` or `$MARKBOOK_FILE` says otherwise. Its format
is described in [docs/format.md](docs/format.md); files written by any older markbook keep
working, and are rewritten in the current format (with a backup of the original) the first
time something changes.

## Code

- `markbook/model.py`: `Bookmark`, folder paths.
- `markbook/collection.py`: `Collection`, the bookmarks in one file.
- `markbook/schema.py`: the current file format and its validation.
- `markbook/migrations/`: one module per format change.
- `markbook/store.py`: loading (with migration) and saving (with backups).
- `markbook/html_format.py`: browser bookmark files, both ways.
- `markbook/cli.py`: the command line.

Tests: `python -m pytest`.
