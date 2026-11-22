"""Rooms running in the server, and everyone watching them.

A client that connects gets the room as it stands (its lines, and the reply being written,
if one is), then every event as it happens. Any client can say something, run more turns
or stop the agent that's speaking. When a run ends, for whatever reason, every client gets
the whole room again, so a reply cut off by a stop shows as it was saved.
"""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from typing import Any

from zwans.room import (
    ROOMS,
    AgentSpec,
    LineAdded,
    ProviderMaker,
    Room,
    RoomError,
    RoomStopped,
    SpeakerStarted,
    SpeakerText,
    load_room,
    recent_rooms,
    router_maker,
)
from zwans.server.live import Busy, HubSettings

log = logging.getLogger(__name__)

type Message = dict[str, Any]

MAX_TURNS = 50  # in one run


class LiveRoom:
    def __init__(self, room: Room) -> None:
        self.room = room
        self.clients: set[asyncio.Queue[Message]] = set()
        self.task: asyncio.Task[None] | None = None
        self.speaking: Message | None = None  # the reply being written: speaker, model, text

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def status(self) -> Message:
        info = self.room.info
        return {
            "type": "room",
            **info.model_dump(),
            "running": self.running,
            "speaking": self.speaking,
            "next": self.room.next_speaker().name,
        }

    def subscribe(self) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self.clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None:
        self.clients.discard(queue)

    def broadcast(self, message: Message) -> None:
        for queue in self.clients:
            queue.put_nowait(message)

    def run(self, turns: int) -> None:
        """Start a run of `turns` turns. Raises Busy while one is running."""
        if self.running:
            raise Busy("The room is already talking. Stop it first, or wait.")
        turns = max(1, min(turns, MAX_TURNS))
        self.task = asyncio.create_task(self._run(turns))

    def say(self, text: str, turns: int) -> None:
        """Add the user's line, then let the agents answer. Raises Busy or RoomError."""
        if self.running:
            raise Busy("Wait for the agent that's speaking, or stop it, before you say something.")
        self.broadcast(self.room.say(text).model_dump())
        if turns > 0:
            self.run(turns)

    def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def _run(self, turns: int) -> None:
        try:
            async for event in self.room.run(turns):
                if isinstance(event, SpeakerStarted):
                    self.speaking = {"speaker": event.speaker, "model": event.model, "text": ""}
                elif isinstance(event, SpeakerText) and self.speaking is not None:
                    self.speaking["text"] += event.text
                elif isinstance(event, LineAdded):
                    self.speaking = None
                self.broadcast(event.model_dump())
        except asyncio.CancelledError:
            self.broadcast(RoomStopped(reason="stopped").model_dump())
        except Exception as exc:  # a bug, or a provider error that isn't a ProviderError
            log.exception("room %s failed", self.room.id)
            self.broadcast(RoomStopped(reason="error", detail=str(exc)).model_dump())
        finally:
            self.speaking = None
            self.task = None
            self.broadcast(self.status())  # the room as saved, cut-off reply and all

    async def close(self) -> None:
        task = self.task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.room.aclose()


class RoomHub:
    """The server's open rooms, by id."""

    def __init__(self, settings: HubSettings) -> None:
        self.settings = settings
        self.folder = settings.config.home / ROOMS
        self.live: dict[str, LiveRoom] = {}
        self._opening = asyncio.Lock()

    def _maker(self) -> ProviderMaker:
        settings = self.settings
        if settings.make_provider is not None:
            factory = settings.make_provider
            return lambda model: factory(settings.config, model)
        return router_maker(settings.config, settings.env)

    async def create(
        self, topic: str, agents: Sequence[AgentSpec], turns: int, budget: float | None
    ) -> LiveRoom:
        """A new room, which starts talking at once unless `turns` is 0. Raises RoomError."""
        live = LiveRoom(Room.new(topic, agents, self._maker(), self.folder, budget))
        self.live[live.room.id] = live
        if turns > 0:
            live.run(turns)
        return live

    async def open(self, room_id: str) -> LiveRoom:
        """A saved room, opened again. Raises RoomError."""
        async with self._opening:
            info = load_room(self.folder, room_id)
            if info.id in self.live:
                return self.live[info.id]
            live = LiveRoom(Room(info, self._maker(), self.folder))
            self.live[info.id] = live
            return live

    def saved(self, limit: int = 50) -> list[Message]:
        return [
            {
                "id": info.id,
                "topic": info.topic,
                "agents": [a.model_dump() for a in info.agents],
                "lines": len(info.lines),
                "dollars": info.dollars,
                "updated_at": info.updated_at,
                "live": info.id in self.live,
                "running": info.id in self.live and self.live[info.id].running,
            }
            for info in recent_rooms(self.folder, limit)
        ]

    async def close(self, room_id: str) -> None:
        live = self.live.pop(room_id, None)
        if live is not None:
            await live.close()

    async def close_all(self) -> None:
        for room_id in list(self.live):
            await self.close(room_id)


def act(live: LiveRoom, message: Message) -> str | None:
    """Do what a client asked. Returns why not, when it can't."""
    kind = message.get("type")
    turns = message.get("turns", 6)
    if not isinstance(turns, int) or isinstance(turns, bool):
        return "turns must be a whole number."
    try:
        if kind == "say":
            live.say(str(message.get("text", "")), turns)
        elif kind == "continue":
            live.run(turns)
        elif kind == "stop":
            live.stop()
        else:
            return f"Unknown message type: {kind!r}"
    except (Busy, RoomError) as exc:
        return str(exc)
    return None
