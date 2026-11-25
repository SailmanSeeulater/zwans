"""stockflow: inventory and orders, event-sourced."""

from stockflow import domain  # noqa: F401  (registers the domain's events and upcasters)
from stockflow.app import App
from stockflow.errors import ConcurrencyError, DomainError, NotFound, StockflowError
from stockflow.repository import Repository
from stockflow.services import Inventory
from stockflow.settings import Settings
from stockflow.store import EventStore, FileEventStore, InMemoryEventStore

__all__ = [
    "App",
    "ConcurrencyError",
    "DomainError",
    "EventStore",
    "FileEventStore",
    "InMemoryEventStore",
    "Inventory",
    "NotFound",
    "Repository",
    "Settings",
    "StockflowError",
]
