"""Errors stockroom raises on purpose. The CLI prints them and exits with exit_code."""


class StockroomError(Exception):
    exit_code = 1


class InvalidInput(StockroomError):
    exit_code = 2


class UnknownSku(StockroomError):
    exit_code = 3

    def __init__(self, sku: str) -> None:
        super().__init__(f"no product with SKU {sku}")
        self.sku = sku


class DuplicateSku(StockroomError):
    exit_code = 4

    def __init__(self, sku: str) -> None:
        super().__init__(f"there is already a product with SKU {sku}")
        self.sku = sku


class InsufficientStock(StockroomError):
    exit_code = 5


class ProductInUse(StockroomError):
    """The product has stock history, so removing it would rewrite the past."""

    exit_code = 6


class CorruptDatabase(StockroomError):
    exit_code = 7
