"""Price lists: named sets of special prices (trade, staff, ...), one price per SKU. A
cart priced with a list pays the list's price for the SKUs on it and the normal price for
everything else."""

from shopdesk.catalog.products import ProductCatalog
from shopdesk.codes import normalize_list_name
from shopdesk.errors import InvalidInput
from shopdesk.events import EventBus
from shopdesk.models import PriceList, ShopData


class PriceLists:
    def __init__(self, data: ShopData, catalog: ProductCatalog, bus: EventBus) -> None:
        self._data = data
        self._catalog = catalog
        self._bus = bus

    def create(self, name: str) -> PriceList:
        name = normalize_list_name(name)
        if name in self._data.price_lists:
            raise InvalidInput(f"Price list {name!r} already exists.")
        price_list = PriceList(name)
        self._data.price_lists[name] = price_list
        return price_list

    def get_list(self, name: str) -> PriceList:
        try:
            return self._data.price_lists[name.strip().lower()]
        except KeyError:
            raise InvalidInput(f"No price list {name!r}.") from None

    def names(self) -> list[str]:
        return sorted(self._data.price_lists)

    def set_price(self, name: str, sku: str, price: int) -> None:
        price_list = self._data.price_lists.get(name) or self.create(name)
        product = self._catalog.get(sku)
        if price < 0:
            raise InvalidInput("A list price can't be negative.")
        price_list.entries[product.sku] = price
        self._bus.publish("pricelist.changed", name=price_list.name, sku=product.sku)

    def remove_price(self, name: str, sku: str) -> None:
        price_list = self.get_list(name)
        if price_list.entries.pop(sku.strip().upper(), None) is None:
            raise InvalidInput(f"{sku} has no price on {name}.")
        self._bus.publish("pricelist.changed", name=price_list.name, sku=sku)

    def lookup(self, name: str | None, sku: str) -> int | None:
        """The list's price for the SKU, or None when there's no list or no entry."""
        if name is None:
            return None
        return self.get_list(name).entries.get(sku)

    def entries(self, name: str) -> list[tuple[str, int]]:
        return sorted(self.get_list(name).entries.items())
