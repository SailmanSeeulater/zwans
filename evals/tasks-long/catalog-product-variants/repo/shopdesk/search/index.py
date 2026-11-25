"""Product search for the shop front and the back office.

The index holds one document per product, built from the catalog and the stock ledger.
It is built on first use and kept current by events: catalog and category changes drop
it (it is rebuilt on the next search), a stock move refreshes the moved product's entry.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from shopdesk.catalog.categories import CategoryTree
from shopdesk.catalog.products import ProductCatalog
from shopdesk.config import Settings
from shopdesk.errors import InvalidInput, UnknownSku
from shopdesk.events import EventBus
from shopdesk.models import Product
from shopdesk.search.facets import compute_facets
from shopdesk.search.tokens import code_tokens, tokenize
from shopdesk.stock.ledger import StockLedger

SORTS = ("relevance", "name", "price", "-price")


@dataclass(frozen=True)
class Doc:
    sku: str
    name: str
    tokens: frozenset[str]
    category: str | None
    categories: frozenset[str]
    brand: str
    price: int
    in_stock: bool
    active: bool


@dataclass(frozen=True)
class SearchResult:
    hits: list[str]
    total: int
    facets: dict[str, dict[str, int]]


class SearchIndex:
    def __init__(self, docs: list[Doc]) -> None:
        self._docs: dict[str, Doc] = {}
        self._postings: dict[str, set[str]] = defaultdict(set)
        for doc in docs:
            self.put(doc)

    def put(self, doc: Doc) -> None:
        self.drop(doc.sku)
        self._docs[doc.sku] = doc
        for token in doc.tokens:
            self._postings[token].add(doc.sku)

    def drop(self, sku: str) -> None:
        old = self._docs.pop(sku, None)
        if old is None:
            return
        for token in old.tokens:
            self._postings[token].discard(sku)

    def docs(self) -> list[Doc]:
        return list(self._docs.values())

    def get(self, sku: str) -> Doc | None:
        return self._docs.get(sku)

    def match(self, terms: list[str]) -> dict[str, float]:
        """Score every document containing all terms: 2 for a whole-token match, 1 for a
        token that merely starts with the term."""
        if not terms:
            return dict.fromkeys(self._docs, 0.0)
        scores: dict[str, float] | None = None
        for term in terms:
            found: dict[str, float] = {}
            for sku in self._postings.get(term, ()):
                found[sku] = 2.0
            for token, skus in self._postings.items():
                if token != term and token.startswith(term):
                    for sku in skus:
                        found.setdefault(sku, 1.0)
            if scores is None:
                scores = found
            else:
                scores = {s: scores[s] + v for s, v in found.items() if s in scores}
        return scores or {}


class SearchService:
    def __init__(
        self,
        catalog: ProductCatalog,
        categories: CategoryTree,
        ledger: StockLedger,
        settings: Settings,
        bus: EventBus,
    ) -> None:
        self._catalog = catalog
        self._categories = categories
        self._ledger = ledger
        self._settings = settings
        self._bus = bus
        self._index: SearchIndex | None = None

    def attach(self) -> None:
        self._bus.subscribe("product.*", self._drop_index)
        self._bus.subscribe("category.*", self._drop_index)
        self._bus.subscribe("stock.moved", self._on_stock_moved)

    def _drop_index(self, topic: str, payload: dict[str, Any]) -> None:
        self._index = None

    def _on_stock_moved(self, topic: str, payload: dict[str, Any]) -> None:
        if self._index is None:
            return
        try:
            product = self._catalog.get(payload["sku"])
        except UnknownSku:
            return
        self._index.put(self.build_doc(product))

    @property
    def index(self) -> SearchIndex:
        if self._index is None:
            self._index = SearchIndex([self.build_doc(p) for p in self._catalog.all()])
        return self._index

    def build_doc(self, product: Product) -> Doc:
        tokens = set(tokenize(product.name))
        tokens.update(tokenize(product.brand))
        tokens.update(tokenize(product.description))
        tokens.update(code_tokens(product.sku))
        if product.barcode:
            tokens.add(product.barcode)
        ancestry: list[str] = []
        if product.category:
            ancestry = [c.slug for c in self._categories.path(product.category)]
            for category in self._categories.path(product.category):
                tokens.update(tokenize(category.name))
        return Doc(
            sku=product.sku,
            name=product.name,
            tokens=frozenset(tokens),
            category=product.category,
            categories=frozenset(ancestry),
            brand=product.brand,
            price=product.price,
            in_stock=self._ledger.on_hand(product.sku) > 0,
            active=product.active,
        )

    def search(
        self,
        text: str = "",
        *,
        category: str | None = None,
        brand: str | None = None,
        in_stock: bool | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        include_inactive: bool = False,
        sort: str = "relevance",
        limit: int | None = None,
    ) -> SearchResult:
        if sort not in SORTS:
            raise InvalidInput(f"Sort by one of {', '.join(SORTS)}.")
        if category is not None:
            category = self._categories.get(category).slug
        scores = self.index.match(tokenize(text) if text.strip() else [])
        docs = []
        for sku, score in scores.items():
            doc = self.index.get(sku)
            if doc is None or (not doc.active and not include_inactive):
                continue
            if category is not None and category not in doc.categories:
                continue
            if brand is not None and doc.brand.lower() != brand.strip().lower():
                continue
            if in_stock is not None and doc.in_stock != in_stock:
                continue
            if price_min is not None and doc.price < price_min:
                continue
            if price_max is not None and doc.price > price_max:
                continue
            docs.append((score, doc))
        docs.sort(key=_sort_key(sort))
        facets = compute_facets([d for _, d in docs], self._settings.price_bands)
        hits = [d.sku for _, d in docs]
        return SearchResult(hits[:limit] if limit else hits, len(hits), facets)


def _sort_key(sort: str):
    if sort == "name":
        return lambda item: (item[1].name.lower(), item[1].sku)
    if sort == "price":
        return lambda item: (item[1].price, item[1].sku)
    if sort == "-price":
        return lambda item: (-item[1].price, item[1].sku)
    return lambda item: (-item[0], item[1].name.lower(), item[1].sku)
