"""A small memoizing decorator with hit and miss counters, for slow lookups."""

import functools
from collections.abc import Callable
from typing import Any


def memoize[F: Callable[..., Any]](func: F) -> F:
    """Remember func's result for each distinct call. All arguments must be hashable."""
    cache: dict[Any, Any] = {}
    stats = {"hits": 0, "misses": 0}

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = args
        if key in cache:
            stats["hits"] += 1
            return cache[key]
        stats["misses"] += 1
        result = func(*args, **kwargs)
        cache[key] = result
        return result

    def cache_clear() -> None:
        cache.clear()
        stats.update(hits=0, misses=0)

    wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
    wrapper.cache_stats = lambda: dict(stats)  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]
