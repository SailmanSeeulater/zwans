"""Checking the in-memory indexes against the data, and rebuilding them.

The indexes are rebuilt every time a CRM is opened, so a mismatch only shows within one
session; `orbit reindex --check` is for finding bugs, not for routine use.
"""

from orbit.index import DedupeIndex, SearchIndex, TagIndex


def check_indexes(crm) -> list[str]:
    problems = []
    fresh_search = SearchIndex(crm.store)
    fresh_search.rebuild()
    if fresh_search.documents() != crm.search_index.documents():
        live, built = crm.search_index.documents(), fresh_search.documents()
        for key in sorted(set(live) | set(built)):
            if live.get(key) != built.get(key):
                problems.append(f"search: {key} differs")
    fresh_dedupe = DedupeIndex(crm.store, crm.settings.phone_match_digits)
    fresh_dedupe.rebuild()
    if fresh_dedupe.keys() != crm.dedupe.keys():
        problems.append("duplicates: index differs from the data")
    fresh_tags = TagIndex(crm.store)
    fresh_tags.rebuild()
    if fresh_tags.snapshot() != crm.tag_index.snapshot():
        problems.append("tags: index differs from the data")
    return problems


def reindex(crm) -> dict[str, int]:
    crm.rebuild_indexes()
    return {
        "search": len(crm.search_index),
        "duplicates": len(crm.dedupe.groups()),
        "tags": len(crm.tag_index.counts()),
    }
