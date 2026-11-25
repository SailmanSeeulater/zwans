"""Errors shopdesk reports to the person at the keyboard.

Every one of them derives from ShopError, so the CLI can print the message and exit 1
instead of a traceback.
"""


class ShopError(Exception):
    """Something the user asked for can't be done."""


class InvalidInput(ShopError):
    pass


class UnknownSku(ShopError):
    def __init__(self, sku: str) -> None:
        super().__init__(f"No product with SKU {sku!r}.")
        self.sku = sku


class DuplicateSku(ShopError):
    def __init__(self, sku: str) -> None:
        super().__init__(f"SKU {sku!r} is already in use.")
        self.sku = sku


class DuplicateBarcode(ShopError):
    def __init__(self, barcode: str, owner: str) -> None:
        super().__init__(f"Barcode {barcode} already belongs to {owner}.")
        self.barcode = barcode
        self.owner = owner


class UnknownCategory(ShopError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"No category {slug!r}.")
        self.slug = slug


class UnknownWarehouse(ShopError):
    def __init__(self, code: str) -> None:
        super().__init__(f"No warehouse {code!r}.")
        self.code = code


class UnknownCart(ShopError):
    def __init__(self, cart_id: str) -> None:
        super().__init__(f"No cart {cart_id!r}.")
        self.cart_id = cart_id


class UnknownOrder(ShopError):
    def __init__(self, number: str) -> None:
        super().__init__(f"No order {number!r}.")
        self.number = number


class UnknownDiscount(ShopError):
    def __init__(self, code: str) -> None:
        super().__init__(f"No discount code {code!r}.")
        self.code = code


class OutOfStock(ShopError):
    def __init__(self, sku: str, wanted: int, available: int) -> None:
        super().__init__(f"Only {available} of {sku} in stock, {wanted} wanted.")
        self.sku = sku
        self.wanted = wanted
        self.available = available


class StoreError(ShopError):
    """The data file can't be read or written."""


class SupplierFileError(ShopError):
    """A supplier file is unusable as a whole (not one bad row)."""
