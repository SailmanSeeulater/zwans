"""A small string key-value store with pluggable backends."""

from kvstore.base import KeyNotFound, Store
from kvstore.factory import UnknownBackend, open_store

__all__ = ["KeyNotFound", "Store", "UnknownBackend", "open_store"]
