# stockroom

Stock levels for a small shop: products, stock coming in and going out, stock counts,
low-stock warnings and a few reports. Run it with `python -m stockroom --help`.

```
python -m stockroom add MUG-01 "Blue mug" --cost 4.25 --reorder-level 10
python -m stockroom receive MUG-01 40 --ref PO-1001
python -m stockroom ship MUG-01 3 --ref web-5521
python -m stockroom count MUG-01 36
python -m stockroom value
```

Several shops (tenants) can share one database: `--tenant NAME` (default `default`) picks
whose stock you are working on, and in code `Inventory(db, tenant="acme")`. Tenants never
see each other's products, stock, alerts or reports, and the same SKU can exist in each.
Data from before tenants existed belongs to the `default` tenant.

Everything lives in one JSON file (`--db`, default `stockroom.json`). `STOCKROOM_NOW`
(e.g. `2026-03-01T09:00:00Z`) fixes the clock, for scripts and tests.

## Layout

| module                  | what                                                         |
|-------------------------|--------------------------------------------------------------|
| `stockroom/storage.py`  | `Database`: the tables, transactions, saving                 |
| `stockroom/cache.py`    | the LRU cache the database keeps for product lookups         |
| `stockroom/search.py`   | the in-memory search index over product names and SKUs       |
| `stockroom/repos.py`    | repositories, the only code that touches tables              |
| `stockroom/inventory.py`| `Inventory`, the service everything else goes through        |
| `stockroom/reports.py`  | read-only reports, straight from the repositories            |
| `stockroom/importer.py` | bulk CSV import of products                                  |
| `stockroom/snapshot.py` | the JSON snapshot the web shop reads                         |
| `stockroom/cli.py`      | the command line                                             |

Stock on hand is never stored: it is the sum of a product's movements (`receive` adds,
`ship` subtracts, `count` adjusts to what was counted). A product whose stock drops to its
reorder level or below gets one alert, at the moment it crosses.

## Tests

`python -m pytest`. `tests/data/` holds a database file written by an earlier release;
it must keep loading.
