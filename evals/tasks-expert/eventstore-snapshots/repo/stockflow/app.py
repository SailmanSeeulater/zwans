"""Everything wired together."""

from pathlib import Path

from stockflow.projections import Projector
from stockflow.repository import Repository
from stockflow.services import Inventory
from stockflow.settings import Settings
from stockflow.store import EventStore, FileEventStore, InMemoryEventStore


class App:
    def __init__(self, store: EventStore, settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else Settings()
        self.store = store
        self.repository = Repository(store, self.settings)
        self.inventory = Inventory(self.repository)
        self.projector = Projector(store, self.settings)

    @classmethod
    def open(cls, directory: str | Path | None = None) -> "App":
        """An app over the data directory (with its stockflow.toml), or in memory."""
        if directory is None:
            return cls(InMemoryEventStore())
        settings = Settings.load(directory)
        return cls(FileEventStore(directory, fsync=settings.fsync), settings)
