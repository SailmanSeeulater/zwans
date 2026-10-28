"""fulfil: orders, stock, invoices and returns for a small web shop."""

from .errors import FulfilError
from .shop import Shop

__all__ = ["FulfilError", "Shop"]
