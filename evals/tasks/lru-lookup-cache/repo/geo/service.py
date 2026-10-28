"""GeoService puts a cache in front of the database."""

import ipaddress
from dataclasses import dataclass

from geo.database import Database, Location


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    size: int


class GeoService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._cache: dict[str, Location] = {}
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _normalise(address: str) -> str:
        # "010.0.0.1 " and "10.0.0.1" are not the same string, but "::1" and "0::1" are the
        # same address, so key the cache on the canonical form.
        return str(ipaddress.ip_address(address.strip()))

    def lookup(self, address: str) -> Location:
        key = self._normalise(address)
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        location = self.database.find(key)  # AddressNotFound propagates and is not cached
        self._cache[key] = location
        return location

    def stats(self) -> CacheStats:
        return CacheStats(hits=self._hits, misses=self._misses, size=len(self._cache))

    def clear_cache(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0
