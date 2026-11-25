# stockflow

Inventory and orders for the warehouse, event-sourced: nothing is ever updated in place.
Every change is an event appended to a store, and the current state of anything is what you
get by applying its events in order.

```
python -m stockflow item register bolt-m8 "M8 bolt" --reorder 200
python -m stockflow item receive bolt-m8 5000 --lot 2024-11-A
python -m stockflow order place o-1001 "Acme Ltd"
python -m stockflow order add o-1001 bolt-m8 300 0.12
python -m stockflow order confirm o-1001
python -m stockflow report stock
```

## Layout

| Module | What it holds |
| --- | --- |
| `events.py` | the event registry (`@event_type`), `NewEvent`, `StoredEvent`, `encode`/`decode` |
| `upcasting.py` | the upcaster registry (`@upcaster`) and `upcast()` |
| `store/` | `EventStore`, `InMemoryEventStore`, `FileEventStore` |
| `aggregate.py` | `Aggregate` and `@handles` |
| `repository.py` | `Repository`: loads aggregates, saves their new events |
| `domain/` | the events, upcasters and aggregates (`StockItem`, `Order`) |
| `services.py` | `Inventory`: the commands, as the CLI runs them |
| `projections/` | read models (`@PROJECTIONS.register`) and the `Projector` |
| `legacy.py` | importing the warehouse scanners' receipts |
| `settings.py` | `Settings`, read from `stockflow.toml` |

## Events and schema versions

An event type is a frozen dataclass registered with `@event_type("Name", version=N)`. Names
are PascalCase, in the past tense (`StockReceived`). Versions are plain integers starting at
1, and the registered class is always the *current* schema.

The store keeps every event exactly as it was written, with the schema version it was
written under, forever. When an event's fields change, bump its version and register an
upcaster from the previous one:

```python
@upcaster("StockReceived", from_version=1)
def received_v1(data):
    return {"quantity": data["count"], "lot": "unlabelled"}
```

Whatever reads events (the repository, the projections) upcasts them first, so no code past
that point ever sees an old shape. Today's old shapes: `StockReceived` v1, `StockAdjusted` v1
and v2, `LineAdded` v1 (see `domain/upcasters.py`).

## Streams, versions and concurrency

Each aggregate has its own stream, named `<prefix>-<id>` (`item-bolt-m8`, `order-o-1001`). A
stream's *version* is the number of events in it; an aggregate loaded from it has the same
`version`.

`store.append(stream, events, expected_version)` appends only if the stream is still at
`expected_version`; otherwise it raises `ConcurrencyError` and writes nothing. The repository
passes the version the aggregate was loaded at, so two people changing the same item at once
can't both win: the second save is rejected and the command can be retried.

`FileEventStore` keeps one JSON line per event in `<data dir>/events.jsonl`. It is safe to
open the same directory from several processes (every CLI command does).

## Aggregates

An aggregate's command methods check the rules and record events; the methods marked
`@handles(EventClass)` apply them. Handlers are looked up by method name each time an event
is applied, and they are the only code that changes state. `as_dict()` gives the state as
plain data; the CLI's `show` commands print it.

`Repository(store, settings)`:

- `load(cls, id)` builds the aggregate from its stream's events (upcast, then applied).
- `save(aggregate)` appends the aggregate's new events, with the version it was loaded at as
  the expected version.
- `stats` counts the work: `loads`, `events_replayed` (events applied to aggregates while
  loading them), `saves` and `events_saved`.

## Projections

Read models are classes registered with `@PROJECTIONS.register("name")`. They handle event
types with `on_<snake_case_type>(stream, data)` methods. The `Projector` feeds them every event
in the store, in global order (`store.read_all()`), upcast. Reports: `stock_levels`,
`low_stock`, `open_orders`.

## Scanner receipts

The warehouse scanners' gateway predates schema versions. `legacy.import_scans(store, scans)`
appends their receipts (`StockReceived` v1) and recounts (`StockAdjusted` v1) straight to the
item streams, exactly as the scanners record them, without going through a repository.
(`python -m stockflow scans import scans.csv` does the same from the gateway's CSV export.)

## Settings

`stockflow.toml` in the data directory; every setting is optional, and an unknown table or
key is an error.

```toml
[store]
fsync = true                 # FileEventStore syncs every append to disk

[inventory]
low_stock_threshold = 5      # for items registered without a reorder level
default_reorder_level = 0
```

In code: `Settings(...)` takes the same settings as keyword arguments, and
`Settings.load(directory)` reads the file.

## Snapshots

Some items have been in the catalogue for years and get tens of thousands of events; loading
one replays every event since it was registered, and every command that touches it pays for
that. Snapshots fix this: a copy of an aggregate's state at some version, kept so that a load
can start there instead of at the beginning. This is how they work:

**Setting.** `snapshot_every`, in the `[store]` table of `stockflow.toml` and as
`Settings(snapshot_every=...)`: a whole number, at least 0, 100 when not set. 0 turns
snapshots off: no snapshot is taken or used, and loads replay the whole stream.

**When one is taken.** After a successful save, if the aggregate's version is
`snapshot_every` or more past the version of its latest usable snapshot (past 0, when it has
none), the repository takes a snapshot of the aggregate at its new version. Nothing else takes
snapshots, apart from the rebuild below. Events appended any other way (the scanner import)
don't, so the next save after an import may find the aggregate well past its last snapshot.

**Loading.** A load starts from the aggregate's latest usable snapshot, if it has one, and
applies only the events after it, upcast exactly as always. `stats.events_replayed` counts the
events applied, so it doesn't count the ones the snapshot stands in for.

**State versions.** Every aggregate class declares `state_version`, a whole number starting at
1, like an event's schema version. Bump it whenever what the aggregate's state means changes:
a new field, a field used differently, or a handler that now treats some event differently. A
snapshot records the `state_version` it was taken under, and is *usable* only while the class
still has that `state_version`. A load that finds the latest snapshot unusable ignores it,
replays the whole stream, and then takes a fresh snapshot at the version it reached, so that
the next load is quick again.

**Where they live.** Snapshots belong to the store, not to a repository: `InMemoryEventStore`
keeps them in memory next to its events, and `FileEventStore` in its data directory. A new
`Repository` on the same store, or a `FileEventStore` reopened on the same directory (another
process, a restart), uses the snapshots already taken. Snapshots are not events: they have no
position, never show up in `read()` or `read_all()`, don't change any stream's version, and
projections never see them.

**Concurrency.** Snapshots change nothing about how saves are checked: a save with a stale
expected version is rejected with `ConcurrencyError`, whatever snapshots exist. A save takes
its snapshot only once the store has accepted its events, so a rejected save leaves no
snapshot behind.

**They never change the answer.** Loading with snapshots gives exactly the aggregate that
replaying the whole stream gives (the same `as_dict()` and `version`), and nothing done to an
aggregate after it is loaded or saved changes a snapshot already taken.

## Tests

```
python -m pytest -q
```
