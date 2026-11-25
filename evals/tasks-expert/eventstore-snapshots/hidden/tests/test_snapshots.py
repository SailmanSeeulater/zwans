"""Snapshots against the README: taken when the rule says, used by every load (and by every
repository and process on the store), never changing what a load gives, ignored and rebuilt
under a new state_version, invisible as events, and no help to a stale save."""

import random

import oracle
import pytest

from stockflow import (
    App,
    ConcurrencyError,
    DomainError,
    FileEventStore,
    InMemoryEventStore,
    Inventory,
    Repository,
    Settings,
)
from stockflow.cli import main
from stockflow.domain import Order, StockItem
from stockflow.errors import SettingsError
from stockflow.legacy import Scan, import_scans
from stockflow.projections import Projector


def rig(every: int, store=None) -> tuple[Repository, Inventory]:
    store = store if store is not None else InMemoryEventStore()
    repository = Repository(store, Settings(snapshot_every=every, fsync=False))
    return repository, Inventory(repository)


def replayed(repository: Repository, cls, id: str):
    before = repository.stats.events_replayed
    aggregate = repository.load(cls, id)
    return aggregate, repository.stats.events_replayed - before


def full_replay(store, stream: str) -> tuple[dict, int]:
    return oracle.replay(stream, store.read(stream))


# -- the setting


def test_the_setting(tmp_path) -> None:
    assert Settings().snapshot_every == 100
    (tmp_path / "stockflow.toml").write_text("[store]\nsnapshot_every = 7\n", encoding="utf-8")
    assert Settings.load(tmp_path).snapshot_every == 7

    for bad in ("-1", "2.5", '"10"'):
        (tmp_path / "stockflow.toml").write_text(f"[store]\nsnapshot_every = {bad}\n", encoding="utf-8")
        with pytest.raises(SettingsError):
            Settings.load(tmp_path)


def test_the_default_applies_without_a_setting() -> None:
    repository = Repository(InMemoryEventStore())
    inventory = Inventory(repository)
    inventory.register_item("bolt", "Bolt")
    for _ in range(129):
        inventory.receive("bolt", 1, "L")

    _, count = replayed(repository, StockItem, "bolt")

    assert count == 30


# -- when snapshots are taken and how loads use them


def test_a_busy_item_loads_from_its_latest_snapshot() -> None:
    repository, inventory = rig(10)
    inventory.register_item("bolt", "Bolt")
    for n in range(94):
        inventory.receive("bolt", n % 7 + 1, f"L{n % 3}")

    item, count = replayed(repository, StockItem, "bolt")

    assert count == 5  # the snapshot is at 90
    assert (item.as_dict(), item.version) == full_replay(repository.store, "item-bolt")


def test_a_save_of_several_events_is_snapshotted_at_its_new_version() -> None:
    repository, inventory = rig(3)
    for sku in ("a", "b", "c"):
        inventory.register_item(sku, sku.upper())
    inventory.place_order("o1", "Acme", [("a", 1, 10), ("b", 2, 20), ("c", 3, 30)])

    order, count = replayed(repository, Order, "o1")

    assert order.version == 4 and count == 0


def test_imported_events_dont_take_snapshots_but_the_next_save_counts_them() -> None:
    repository, inventory = rig(4)
    inventory.register_item("bolt", "Bolt")  # 1
    inventory.receive("bolt", 5, "A")  # 2
    import_scans(repository.store, [Scan("bolt", "in", 3)] * 5)  # 3..7

    _, count = replayed(repository, StockItem, "bolt")
    assert count == 7

    inventory.receive("bolt", 1, "A")  # 8: 8 - 0 >= 4, so a snapshot at 8
    item, count = replayed(repository, StockItem, "bolt")
    assert count == 0
    assert item.on_hand == 21


def test_snapshots_off() -> None:
    repository, inventory = rig(0)
    inventory.register_item("bolt", "Bolt")
    for _ in range(20):
        inventory.receive("bolt", 1, "L")

    _, count = replayed(repository, StockItem, "bolt")

    assert count == 21


def test_old_shapes_after_a_snapshot_are_upcast() -> None:
    repository, inventory = rig(2)
    inventory.register_item("bolt", "Bolt")  # 1
    inventory.receive("bolt", 10, "A")  # 2 -> snapshot
    inventory.receive("bolt", 4, "B")  # 3
    import_scans(repository.store, [Scan("bolt", "in", 6), Scan("bolt", "fix", -2)])  # 4, 5

    item, count = replayed(repository, StockItem, "bolt")

    assert count == 3
    assert item.as_dict()["lots"] == {"A": 10, "B": 4, "unlabelled": 6}
    assert item.on_hand == 18


# -- where snapshots live


def test_a_new_repository_on_the_same_store_uses_the_snapshots() -> None:
    repository, inventory = rig(5)
    inventory.register_item("bolt", "Bolt")
    for _ in range(11):
        inventory.receive("bolt", 2, "L")

    other = Repository(repository.store, Settings(snapshot_every=5))
    item, count = replayed(other, StockItem, "bolt")

    assert count == 2 and item.on_hand == 22


def test_snapshots_survive_reopening_a_file_store(tmp_path) -> None:
    repository, inventory = rig(5, FileEventStore(tmp_path, fsync=False))
    inventory.register_item("bolt", "Bolt")
    for _ in range(12):
        inventory.receive("bolt", 3, "L")

    reopened = Repository(FileEventStore(tmp_path, fsync=False), Settings(snapshot_every=5))
    item, count = replayed(reopened, StockItem, "bolt")

    assert count == 3
    assert (item.as_dict(), item.version) == full_replay(reopened.store, "item-bolt")


def test_the_command_line_takes_snapshots_per_its_settings_file(tmp_path) -> None:
    (tmp_path / "stockflow.toml").write_text(
        "[store]\nfsync = false\nsnapshot_every = 3\n", encoding="utf-8"
    )
    data = ["--data", str(tmp_path)]
    assert main(data + ["item", "register", "bolt", "Bolt"]) == 0
    for _ in range(7):
        assert main(data + ["item", "receive", "bolt", "2"]) == 0

    app = App.open(tmp_path)
    item, count = replayed(app.repository, StockItem, "bolt")

    assert count == 2 and item.on_hand == 14


def test_snapshots_are_not_events() -> None:
    repository, inventory = rig(1)
    plain, plain_inventory = rig(0)
    for service in (inventory, plain_inventory):
        service.register_item("bolt", "Bolt", 3)
        service.receive("bolt", 10, "A")
        service.place_order("o1", "Acme", [("bolt", 4, 250)])
        service.confirm_order("o1")
        service.adjust("bolt", -1, "damaged")

    store = repository.store
    assert store.version("item-bolt") == 4 and len(store.read("item-bolt")) == 4
    assert store.version("order-o1") == 3
    assert [(e.stream, e.type) for e in store.read_all()] == [
        (e.stream, e.type) for e in plain.store.read_all()
    ]
    snapshotted, without = Projector(store), Projector(plain.store)
    for name in ("stock_levels", "low_stock", "open_orders"):
        assert snapshotted.result(name) == without.result(name)


# -- state versions


def test_a_snapshot_from_another_state_version_is_ignored_and_rebuilt(monkeypatch) -> None:
    repository, inventory = rig(3)
    inventory.register_item("bolt", "Bolt")  # 1
    inventory.receive("bolt", 10, "A")  # 2
    inventory.adjust("bolt", -2, "damaged")  # 3 -> snapshot
    inventory.receive("bolt", 5, "B")  # 4
    assert replayed(repository, StockItem, "bolt")[1] == 1

    # A new release: damaged stock is tracked elsewhere, so it no longer leaves on_hand.
    keep = StockItem.when_adjusted

    def when_adjusted(self, event) -> None:
        if event.reason != "damaged":
            keep(self, event)

    monkeypatch.setattr(StockItem, "when_adjusted", when_adjusted)
    monkeypatch.setattr(StockItem, "state_version", 2)

    item, count = replayed(repository, StockItem, "bolt")
    assert count == 4
    assert item.on_hand == 15 and item.version == 4

    item, count = replayed(repository, StockItem, "bolt")
    assert count == 0
    assert item.on_hand == 15


# -- concurrency


def test_a_stale_save_is_rejected_and_leaves_no_snapshot() -> None:
    repository, inventory = rig(1)
    inventory.register_item("bolt", "Bolt")
    inventory.receive("bolt", 10, "A")
    other = Repository(repository.store, Settings(snapshot_every=1))

    mine = repository.load(StockItem, "bolt")
    theirs = other.load(StockItem, "bolt")
    mine.receive(5, "B")
    theirs.receive(700, "Z")
    theirs.adjust(-3, "damaged")
    repository.save(mine)
    with pytest.raises(ConcurrencyError):
        other.save(theirs)

    fresh = Repository(repository.store, Settings(snapshot_every=1))
    item, count = replayed(fresh, StockItem, "bolt")
    assert count == 0
    assert item.as_dict()["lots"] == {"A": 10, "B": 5}
    assert item.version == 3


def test_a_stale_save_is_rejected_even_from_a_snapshot() -> None:
    repository, inventory = rig(2)
    inventory.register_item("bolt", "Bolt")
    inventory.receive("bolt", 10, "A")  # snapshot at 2
    first = repository.load(StockItem, "bolt")
    second = Repository(repository.store, Settings(snapshot_every=2)).load(StockItem, "bolt")

    first.receive(1, "B")
    repository.save(first)
    second.receive(1, "C")
    with pytest.raises(ConcurrencyError):
        Repository(repository.store, Settings(snapshot_every=2)).save(second)

    loaded = repository.load(StockItem, "bolt")
    loaded.receive(1, "D")
    repository.save(loaded)
    assert full_replay(repository.store, "item-bolt")[0]["lots"] == {"A": 10, "B": 1, "D": 1}


# -- a loaded aggregate doesn't reach back into its snapshot


def test_changing_a_loaded_aggregate_doesnt_change_its_snapshot() -> None:
    repository, inventory = rig(2)
    inventory.register_item("bolt", "Bolt")
    inventory.receive("bolt", 5, "A")  # snapshot at 2
    inventory.receive("bolt", 3, "A")  # 3: loaded from the snapshot, then saved
    inventory.place_order("o1", "Acme", [("bolt", 1, 100)])  # snapshot at 2
    inventory.add_line("o1", "bolt", 2, 100)
    inventory.add_line("o1", "bolt", 4, 90)  # snapshot at 4

    item = repository.load(StockItem, "bolt")
    item.lots["A"] = 999
    item.reservations["ghost"] = 1

    assert repository.load(StockItem, "bolt").as_dict()["lots"] == {"A": 8}
    assert repository.load(StockItem, "bolt").reserved == 0
    assert repository.load(Order, "o1").as_dict()["lines"] == {
        "bolt": {"quantity": 7, "unit_price_cents": 90}
    }


# -- anything at all


SKUS = ["s1", "s2", "s3", "s4"]
ORDERS = ["o1", "o2", "o3", "o4", "o5"]
LOTS = ["L1", "L2", "L3"]
REASONS = ["damaged", "recount", "found"]


class World:
    def __init__(self, every: int, file_dir=None) -> None:
        self.every = every
        self.file_dir = file_dir
        self.settings = Settings(snapshot_every=every, fsync=False)
        self.store = FileEventStore(file_dir, fsync=False) if file_dir else InMemoryEventStore()
        self.reopen(new_store=False)
        self.rule = oracle.SnapshotRule(every)

    def reopen(self, new_store: bool = True) -> None:
        if new_store and self.file_dir:
            self.store = FileEventStore(self.file_dir, fsync=False)
        self.repository = Repository(self.store, self.settings)
        self.inventory = Inventory(self.repository)

    def versions(self) -> dict[str, int]:
        return {stream: self.store.version(stream) for stream in self.store.streams()}

    def registered(self) -> list[str]:
        return [sku for sku in SKUS if self.store.version(f"item-{sku}") > 0]


def act(world: World, rng: random.Random) -> str:
    inventory = world.inventory
    sku, order_id = rng.choice(SKUS), rng.choice(ORDERS)
    roll = rng.random()
    if roll < 0.1:
        inventory.register_item(sku, sku.upper(), rng.choice([0, 3, 10]))
        return f"register {sku}"
    if roll < 0.35:
        inventory.receive(sku, rng.randint(1, 20), rng.choice(LOTS))
        return f"receive {sku}"
    if roll < 0.45:
        inventory.adjust(sku, rng.choice([-4, -2, -1, 1, 2, 5]), rng.choice(REASONS))
        return f"adjust {sku}"
    if roll < 0.58:
        lines = [(rng.choice(SKUS), rng.randint(1, 6), rng.randint(50, 500)) for _ in range(rng.randint(0, 3))]
        inventory.place_order(order_id, rng.choice(["Acme", "Bobs"]), lines)
        return f"place {order_id} {lines}"
    if roll < 0.68:
        inventory.add_line(order_id, sku, rng.randint(1, 6), rng.randint(50, 500))
        return f"add {order_id} {sku}"
    if roll < 0.73:
        inventory.remove_line(order_id, sku)
        return f"remove {order_id} {sku}"
    if roll < 0.85:
        inventory.confirm_order(order_id)
        return f"confirm {order_id}"
    if roll < 0.91:
        inventory.cancel_order(order_id, rng.choice(["", "late"]))
        return f"cancel {order_id}"
    inventory.ship_order(order_id)
    return f"ship {order_id}"


@pytest.mark.parametrize("seed", range(120))
def test_any_history_loads_the_same_with_snapshots(seed: int, tmp_path) -> None:
    rng = random.Random(seed)
    every = rng.choice([1, 2, 2, 3, 3, 5, 8, 0])
    world = World(every, tmp_path / "data" if seed % 3 == 0 else None)
    trail: list[str] = []

    for step in range(45):
        before = world.versions()
        by_saves = True
        roll = rng.random()
        try:
            if roll < 0.82:
                trail.append(act(world, rng))
            elif roll < 0.9:
                by_saves = False
                scans = [
                    Scan(rng.choice(SKUS), *rng.choice([("in", rng.randint(1, 9)), ("fix", rng.choice([-2, -1, 3]))]))
                    for _ in range(rng.randint(1, 3))
                ]
                import_scans(world.store, scans)
                trail.append(f"import {scans}")
            elif roll < 0.96:
                registered = world.registered()
                if registered:
                    sku = rng.choice(registered)
                    other = Repository(world.store, world.settings)
                    mine = world.repository.load(StockItem, sku)
                    theirs = other.load(StockItem, sku)
                    mine.receive(rng.randint(1, 5), "M")
                    for _ in range(rng.randint(1, 3)):
                        theirs.receive(rng.randint(100, 200), "T")
                    world.repository.save(mine)
                    with pytest.raises(ConcurrencyError):
                        other.save(theirs)
                    trail.append(f"conflict on {sku}")
            else:
                world.reopen()
                trail.append("reopen")
        except DomainError as error:
            trail.append(f"refused: {error}")
        if by_saves:
            for stream, version in world.versions().items():
                if version != before.get(stream, 0):
                    world.rule.saved(stream, version)

        total = 0
        for stream in world.store.streams():
            events = world.store.read(stream)
            version = world.store.version(stream)
            where = f"seed {seed} (snapshot_every={every}), step {step}, {stream}"
            assert [e.position for e in events] == list(range(1, version + 1)), where
            assert all(e.type in oracle.KNOWN_TYPES for e in events), where
            total += version
            want, want_version = oracle.replay(stream, events)
            repository = world.repository if rng.random() < 0.7 else Repository(world.store, world.settings)
            cls = StockItem if stream.startswith("item-") else Order
            aggregate, count = replayed(repository, cls, stream.split("-", 1)[1])
            history = "\n".join(trail[-10:])
            assert aggregate.as_dict() == want, f"{where}: loaded {aggregate.as_dict()}, a full replay gives {want}\n{history}"
            assert aggregate.version == want_version, f"{where}: version {aggregate.version}, should be {want_version}\n{history}"
            should = world.rule.replayed_by_load(stream, version)
            assert count == should, f"{where}: the load replayed {count} events, should be {should}\n{history}"
        assert len(world.store.read_all()) == total
