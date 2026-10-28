import pytest

from geo.database import AddressNotFound, Database, Location
from geo.service import CacheStats, GeoService

NETWORKS = {
    "10.0.0.0/8": Location("NL", "Amsterdam"),
    "10.1.0.0/16": Location("BE", "Ghent"),
    "2001:db8::/32": Location("PT", "Porto"),
}


def test_lookup() -> None:
    service = GeoService(Database(NETWORKS))

    assert service.lookup("10.2.3.4") == Location("NL", "Amsterdam")
    assert service.lookup("10.1.3.4") == Location("BE", "Ghent")
    assert service.lookup("2001:db8::1") == Location("PT", "Porto")


def test_repeat_lookups_hit_the_cache() -> None:
    database = Database(NETWORKS)
    service = GeoService(database)

    service.lookup("10.1.0.1")
    service.lookup(" 10.1.0.1")
    service.lookup("10.2.0.1")

    assert database.queries == 2
    assert service.stats() == CacheStats(hits=1, misses=2, size=2)


def test_unknown_addresses_are_not_cached() -> None:
    service = GeoService(Database(NETWORKS))

    with pytest.raises(AddressNotFound):
        service.lookup("192.168.0.1")
    assert service.stats().size == 0


def test_clear_cache() -> None:
    database = Database(NETWORKS)
    service = GeoService(database)
    service.lookup("10.1.0.1")

    service.clear_cache()
    service.lookup("10.1.0.1")

    assert database.queries == 2
    assert service.stats() == CacheStats(hits=0, misses=1, size=1)
