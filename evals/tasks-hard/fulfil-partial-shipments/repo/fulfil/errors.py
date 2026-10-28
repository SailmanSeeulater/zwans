class FulfilError(Exception):
    """Anything a caller asked for that cannot be done."""


class UnknownProduct(FulfilError):
    pass


class UnknownOrder(FulfilError):
    pass


class OutOfStock(FulfilError):
    pass


class InvalidState(FulfilError):
    """The request is fine, but not for an order in this state."""


class InvalidRequest(FulfilError):
    """The request makes no sense on its own (zero quantities, unknown coupons...)."""
