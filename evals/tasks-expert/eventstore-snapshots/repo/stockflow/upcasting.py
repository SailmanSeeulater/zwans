"""Bringing stored event data up to the current schema.

The store keeps events exactly as they were written, with the schema version they were
written under. Readers never see old shapes: each upcaster turns data of one version of an
event into the next version, and upcast() chains them up to the current one.
"""

import copy
from typing import Any, Callable

from stockflow.errors import UpcastError
from stockflow.events import StoredEvent, current_version

Upcaster = Callable[[dict[str, Any]], dict[str, Any]]

_UPCASTERS: dict[tuple[str, int], Upcaster] = {}


def upcaster(event: str, *, from_version: int) -> Callable[[Upcaster], Upcaster]:
    """Register a function taking `event` data at `from_version` to `from_version + 1`."""

    def register(function: Upcaster) -> Upcaster:
        key = (event, from_version)
        if key in _UPCASTERS:
            raise ValueError(f"two upcasters for {event} v{from_version}")
        _UPCASTERS[key] = function
        return function

    return register


def upcast(event: str, schema: int, data: dict[str, Any]) -> dict[str, Any]:
    target = current_version(event)
    if schema > target:
        raise UpcastError(f"{event} v{schema} is newer than this code (v{target})")
    result = copy.deepcopy(data)
    while schema < target:
        step = _UPCASTERS.get((event, schema))
        if step is None:
            raise UpcastError(f"no upcaster for {event} v{schema}")
        result = step(result)
        schema += 1
    return result


def upcast_stored(stored: StoredEvent) -> dict[str, Any]:
    return upcast(stored.type, stored.schema, stored.data)


def registered() -> list[tuple[str, int]]:
    return sorted(_UPCASTERS)
