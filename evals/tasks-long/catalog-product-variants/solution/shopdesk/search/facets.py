"""Facet counts for a set of search results: how many results fall in each category,
brand, price band and stock state, and how many have a variant with each option value,
for the filter sidebar."""

from collections import Counter
from collections.abc import Sequence
from typing import Protocol

from shopdesk.config import band_labels, band_of


class Faceted(Protocol):
    category: str | None
    brand: str
    price: int
    in_stock: bool
    variant_options: tuple[frozenset[tuple[str, str]], ...]


def compute_facets(docs: Sequence[Faceted], bands: list[int]) -> dict[str, dict[str, int]]:
    categories: Counter[str] = Counter()
    brands: Counter[str] = Counter()
    prices: Counter[str] = Counter({label: 0 for label in band_labels(bands)})
    stock: Counter[str] = Counter({"yes": 0, "no": 0})
    options: dict[str, Counter[str]] = {}
    for doc in docs:
        for name, value in set().union(*doc.variant_options):
            options.setdefault(name, Counter())[value] += 1
        if doc.category:
            categories[doc.category] += 1
        if doc.brand:
            brands[doc.brand] += 1
        prices[band_of(doc.price, bands)] += 1
        stock["yes" if doc.in_stock else "no"] += 1
    return {
        "category": dict(sorted(categories.items())),
        "brand": dict(sorted(brands.items())),
        "price": dict(prices),
        "in_stock": dict(stock),
        "options": {name: dict(sorted(options[name].items())) for name in sorted(options)},
    }
