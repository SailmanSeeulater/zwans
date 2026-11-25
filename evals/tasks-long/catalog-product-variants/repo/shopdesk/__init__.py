"""shopdesk: the back office of a small shop."""

from shopdesk.errors import ShopError
from shopdesk.models import ShopData
from shopdesk.shop import Shop

__all__ = ["Shop", "ShopData", "ShopError"]
__version__ = "2.4.0"
