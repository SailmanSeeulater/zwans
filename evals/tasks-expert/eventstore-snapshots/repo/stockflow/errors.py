"""Every error stockflow raises on purpose."""


class StockflowError(Exception):
    """Base class."""


class ConcurrencyError(StockflowError):
    """An append whose expected version is not the stream's version: someone else wrote first."""

    def __init__(self, stream: str, expected: int, actual: int) -> None:
        super().__init__(f"{stream}: expected version {expected}, but it is at {actual}")
        self.stream = stream
        self.expected = expected
        self.actual = actual


class NotFound(StockflowError):
    """No events for that aggregate."""


class DomainError(StockflowError):
    """A command the domain rules don't allow (not enough stock, order already shipped, ...)."""


class EventShapeError(StockflowError):
    """Event data that doesn't match the event's current schema."""


class UpcastError(StockflowError):
    """Stored event data that can't be brought up to the current schema."""


class SettingsError(StockflowError):
    """A stockflow.toml that can't be used."""


class StoreError(StockflowError):
    """The event store can't do what was asked (bad stream name, damaged file, ...)."""
