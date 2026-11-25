"""The category tree. Categories nest (Home > Kitchen > Mugs); a product sits in one."""

from shopdesk.codes import normalize_slug
from shopdesk.errors import InvalidInput, UnknownCategory
from shopdesk.events import EventBus
from shopdesk.models import Category, ShopData

MAX_DEPTH = 6


class CategoryTree:
    def __init__(self, data: ShopData, bus: EventBus) -> None:
        self._data = data
        self._bus = bus

    def add(self, slug: str, name: str, parent: str | None = None) -> Category:
        slug = normalize_slug(slug)
        if slug in self._data.categories:
            raise InvalidInput(f"Category {slug!r} already exists.")
        if not name.strip():
            raise InvalidInput("A category needs a name.")
        if parent is not None:
            parent = self.get(parent).slug
            if len(self.path(parent)) >= MAX_DEPTH:
                raise InvalidInput(f"Categories nest at most {MAX_DEPTH} deep.")
        category = Category(slug, name.strip(), parent)
        self._data.categories[slug] = category
        self._bus.publish("category.added", slug=slug)
        return category

    def get(self, slug: str) -> Category:
        try:
            return self._data.categories[slug.strip().lower()]
        except KeyError:
            raise UnknownCategory(slug) from None

    def exists(self, slug: str) -> bool:
        return slug.strip().lower() in self._data.categories

    def rename(self, slug: str, name: str) -> None:
        self.get(slug).name = name.strip()
        self._bus.publish("category.changed", slug=slug)

    def move(self, slug: str, parent: str | None) -> None:
        category = self.get(slug)
        if parent is not None:
            parent = self.get(parent).slug
            if parent == category.slug or category.slug in self.ancestors(parent):
                raise InvalidInput("A category can't sit inside itself.")
        category.parent = parent
        self._bus.publish("category.changed", slug=slug)

    def all(self) -> list[Category]:
        return sorted(self._data.categories.values(), key=lambda c: self.breadcrumb(c.slug))

    def children(self, slug: str | None) -> list[Category]:
        return sorted(
            (c for c in self._data.categories.values() if c.parent == slug),
            key=lambda c: c.name,
        )

    def ancestors(self, slug: str) -> list[str]:
        """Slugs from the root down to the category's parent."""
        chain = []
        current = self.get(slug).parent
        while current is not None:
            chain.append(current)
            current = self._data.categories[current].parent
        return list(reversed(chain))

    def path(self, slug: str) -> list[Category]:
        return [self._data.categories[s] for s in self.ancestors(slug)] + [self.get(slug)]

    def breadcrumb(self, slug: str, separator: str = " > ") -> str:
        return separator.join(c.name for c in self.path(slug))

    def descendants(self, slug: str) -> set[str]:
        """The category and everything below it."""
        root = self.get(slug).slug
        found = {root}
        changed = True
        while changed:
            changed = False
            for category in self._data.categories.values():
                if category.parent in found and category.slug not in found:
                    found.add(category.slug)
                    changed = True
        return found
