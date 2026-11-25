from orbit.clock import Clock
from orbit.config import Settings
from orbit.events import Bus, Event
from orbit.store import Store


class Service:
    def __init__(self, store: Store, bus: Bus, clock: Clock, settings: Settings) -> None:
        self.store = store
        self.bus = bus
        self.clock = clock
        self.settings = settings

    def publish(self, name: str, payload: dict, contact_ids=()) -> None:
        self.bus.publish(Event(name, payload, tuple(contact_ids)))
