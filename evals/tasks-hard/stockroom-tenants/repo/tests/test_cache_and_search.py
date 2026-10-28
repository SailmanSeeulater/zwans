import pytest
from stockroom.cache import LookupCache
from stockroom.search import SearchIndex, tokens


def test_the_cache_forgets_the_least_recently_used() -> None:
    cache = LookupCache(capacity=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert "b" not in cache
    assert (cache.get("a"), cache.get("c"), cache.get("b")) == (1, 3, None)
    assert (cache.hits, cache.misses) == (3, 1)


def test_cache_invalidation() -> None:
    cache = LookupCache()
    cache.put(("x", 1), "value")
    cache.invalidate(("x", 1))
    cache.invalidate("never there")
    assert len(cache) == 0
    with pytest.raises(ValueError):
        LookupCache(capacity=0)


def test_tokens() -> None:
    assert tokens("Green tea, 100 g") == {"green", "tea", "100", "g"}


def test_every_query_token_must_prefix_match() -> None:
    index = SearchIndex()
    index.add("MUG-01", "MUG-01 Blue mug")
    index.add("KET-02", "KET-02 Blue kettle")
    assert index.search("blu") == ["KET-02", "MUG-01"]
    assert index.search("blu mu") == ["MUG-01"]
    assert index.search("") == []
    assert index.search("red") == []


def test_re_adding_replaces_and_removing_forgets() -> None:
    index = SearchIndex()
    index.add("MUG-01", "Blue mug")
    index.add("MUG-01", "Red mug")
    assert index.search("blue") == []
    index.remove("MUG-01")
    assert index.search("mug") == []
    assert len(index) == 0


def test_any_hashable_key_works() -> None:
    index = SearchIndex()
    index.add(("a", 1), "one")
    index.rebuild([(("b", 2), "two"), (("a", 1), "one too")])
    assert index.search("one") == [("a", 1)]
    assert index.search("two") == [("b", 2)]
