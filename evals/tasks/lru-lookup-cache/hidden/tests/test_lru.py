import pytest

from geo.database import AddressNotFound, Database, Location
from geo.service import CacheStats, GeoService

NETWORKS = {"10.0.0.0/8": Location("NL", "Amsterdam"), "2001:db8::/32": Location("PT", "Porto")}


def make(max_size: int) -> tuple[GeoService, Database]:
    database = Database(NETWORKS)
    return GeoService(database, max_size=max_size), database


def test_default_size_is_1024() -> None:
    service, database = make(1024)
    default = GeoService(Database(NETWORKS))
    for i in range(1030):
        address = f"10.0.{i // 256}.{i % 256}"
        service.lookup(address)
        default.lookup(address)

    assert default.stats() == service.stats()
    assert default.stats().size == 1024
    assert default.stats().evictions == 6


def test_least_recently_used_is_dropped() -> None:
    service, database = make(2)

    service.lookup("10.0.0.1")
    service.lookup("10.0.0.2")
    service.lookup("10.0.0.3")  # drops .1

    assert service.stats() == CacheStats(hits=0, misses=3, size=2, evictions=1)
    service.lookup("10.0.0.2")
    service.lookup("10.0.0.3")
    assert database.queries == 3
    service.lookup("10.0.0.1")
    assert database.queries == 4


def test_a_hit_counts_as_a_use() -> None:
    service, database = make(2)

    service.lookup("10.0.0.1")
    service.lookup("10.0.0.2")
    service.lookup("10.0.0.1")  # .1 is now the most recent
    service.lookup("10.0.0.3")  # so .2 is dropped

    service.lookup("10.0.0.1")
    assert database.queries == 3
    service.lookup("10.0.0.2")
    assert database.queries == 4
    assert service.stats() == CacheStats(hits=2, misses=4, size=2, evictions=2)


def test_size_one() -> None:
    service, database = make(1)

    for address in ["10.0.0.1", "10.0.0.1", "10.0.0.2", "10.0.0.1"]:
        service.lookup(address)

    assert database.queries == 3
    assert service.stats() == CacheStats(hits=1, misses=3, size=1, evictions=2)


def test_size_zero_turns_caching_off() -> None:
    service, database = make(0)

    for _ in range(3):
        assert service.lookup("2001:db8::7") == Location("PT", "Porto")

    assert database.queries == 3
    assert service.stats() == CacheStats(hits=0, misses=3, size=0, evictions=0)


def test_negative_size() -> None:
    with pytest.raises(ValueError):
        GeoService(Database(NETWORKS), max_size=-1)


def test_failed_lookups_do_not_evict() -> None:
    service, database = make(1)
    service.lookup("10.0.0.1")

    with pytest.raises(AddressNotFound):
        service.lookup("192.168.1.1")

    service.lookup("10.0.0.1")
    assert database.queries == 2
    assert service.stats().evictions == 0


def test_equivalent_addresses_share_an_entry() -> None:
    service, database = make(2)

    service.lookup("2001:db8::1")
    service.lookup("2001:DB8:0::1")
    service.lookup(" 2001:db8::1 ")

    assert database.queries == 1
    assert service.stats().size == 1


def test_clear_cache_resets_evictions() -> None:
    service, _ = make(1)
    service.lookup("10.0.0.1")
    service.lookup("10.0.0.2")

    service.clear_cache()

    assert service.stats() == CacheStats(hits=0, misses=0, size=0, evictions=0)
