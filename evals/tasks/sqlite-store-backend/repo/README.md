# kvstore

A small string key-value store with pluggable backends.

```python
from kvstore import open_store

with open_store("json://settings.json") as store:
    store.set("theme", "dark")
    store.get("theme")        # "dark"
    store.keys("th")          # ["theme"]
```

## Store URLs

A store is opened from a URL of the form `<scheme>://<location>`. Everything after `://`
is the location, used as given: `json://data.json` is relative to the current folder and
`json:///var/lib/app/data.json` is absolute.

| scheme   | backend          | location                  |
|----------|------------------|---------------------------|
| `memory` | `MemoryStore`    | ignored (`memory://`)     |
| `json`   | `JsonFileStore`  | path of the JSON file     |

An unknown scheme raises `UnknownBackend`.

## Behaviour every backend shares

See the docstrings in `kvstore/base.py`. The contract tests in `tests/test_contract.py` run
against every backend.

## Command line

```
python -m kvstore --store json://data.json set greeting hello
python -m kvstore --store json://data.json get greeting
python -m kvstore --store json://data.json keys [prefix]
python -m kvstore --store json://data.json del greeting
```
