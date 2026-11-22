"""A room: several agents, each on a model of its own, talking in one conversation.

The room keeps one shared list of lines. Before an agent speaks, that list is rewritten from
its point of view: its own lines become assistant messages and everyone else's become user
messages, tagged with who said them ("[Bo]: ..."). Every model sees the same conversation in
the shape any chat API takes, so Claude, an OpenAI-compatible server and a local model can
share a room.

Agents speak one at a time. The next is whoever the last line mentions as @Name, or else whoever
has waited longest. A run stops after a number of turns, or before a turn once
the room has spent its budget. The user can say something between runs, as one more voice.

Rooms have no tools: agents only talk (and search the web, where their provider offers it).
Each room is saved as JSON under the home's rooms/ folder after every line.
"""

import re
import secrets
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from zwans.config import Config
from zwans.events import TextDelta
from zwans.messages import Message, TextBlock
from zwans.pricing import cost
from zwans.providers.base import ModelResponse, Provider, ProviderError
from zwans.providers.catalog import canonical
from zwans.providers.router import ModelRouter

ROOMS = "rooms"  # in Zwans's home: one JSON file per room
USER = "User"  # the person's name in the room, as agents see it
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,23}$")
MAX_AGENTS = 8

type ProviderMaker = Callable[[str], Provider]  # a model's name to a provider for it


class RoomError(Exception):
    """A room can't be made, found or run as asked; the message says why."""


class AgentSpec(BaseModel):
    name: str
    model: str
    persona: str = ""  # who they are in the room, as "a skeptical security reviewer"


class Line(BaseModel):
    speaker: str  # an agent's name, or USER
    text: str
    model: str = ""  # the model that wrote it; empty for the user
    dollars: float | None = None  # what writing it cost, when the model's price is known
    cut: bool = False  # stopped partway through


class RoomInfo(BaseModel):
    id: str
    topic: str
    agents: list[AgentSpec]
    lines: list[Line] = Field(default_factory=list)
    dollars: float = 0.0
    unpriced: list[str] = Field(default_factory=list)  # models whose price isn't known
    budget: float | None = None  # the most it may spend in all, in dollars
    created_at: str = ""
    updated_at: str = ""


# -- what a room emits as it runs, for the CLI to print and the server to pass on


class SpeakerStarted(BaseModel):
    type: Literal["speaker_started"] = "speaker_started"
    speaker: str
    model: str


class SpeakerText(BaseModel):
    type: Literal["speaker_text"] = "speaker_text"
    speaker: str
    text: str  # the next piece of the reply


class LineAdded(BaseModel):
    type: Literal["line_added"] = "line_added"
    line: Line
    dollars: float  # the room's total so far


class RoomStopped(BaseModel):
    type: Literal["room_stopped"] = "room_stopped"
    reason: Literal["turns", "budget", "stopped", "error"]
    detail: str = ""


type RoomEvent = SpeakerStarted | SpeakerText | LineAdded | RoomStopped


def check_agents(agents: Sequence[AgentSpec]) -> None:
    """Raises RoomError unless the agents can share a room."""
    if not agents:
        raise RoomError("A room needs at least one agent.")
    if len(agents) > MAX_AGENTS:
        raise RoomError(f"A room can have at most {MAX_AGENTS} agents.")
    seen: set[str] = set()
    for agent in agents:
        if not NAME.match(agent.name):
            raise RoomError(
                f"{agent.name!r} can't be an agent's name: use a letter, then up to 23 "
                "letters, digits, - or _."
            )
        if agent.name.lower() == USER.lower():
            raise RoomError(f"{USER} is the name the room gives you; pick another.")
        if agent.name.lower() in seen:
            raise RoomError(f"Two agents are called {agent.name}; give each its own name.")
        seen.add(agent.name.lower())
        if not agent.model.strip():
            raise RoomError(f"{agent.name} needs a model.")


def parse_agent(spec: str) -> AgentSpec:
    """`name=model`, as the CLI takes it. The model may hold colons, as ollama/qwen3:8b."""
    name, sep, model = spec.partition("=")
    if not sep or not name.strip() or not model.strip():
        raise RoomError(f"{spec!r} isn't name=model, as ada=claude-opus-5-5.")
    return AgentSpec(name=name.strip(), model=model.strip())


class Room:
    def __init__(
        self,
        info: RoomInfo,
        make_provider: ProviderMaker,
        folder: Path | None = None,
        budget: float | None = None,
    ) -> None:
        """`folder` is where the room is saved (the home's rooms/), or None to keep it in memory.
        `budget`, when given, replaces the room's own: the most it may spend in all, in
        dollars. A run stops before a turn once that's reached. Raises RoomError when an
        agent's model can't be used."""
        check_agents(info.agents)
        self.info = info
        self.folder = folder
        if budget is not None:
            info.budget = budget
        self.providers: dict[str, Provider] = {}
        for agent in info.agents:
            try:
                self.providers[agent.name] = make_provider(agent.model)
            except Exception as exc:  # ConfigError, ModelError: the model or its key
                raise RoomError(f"{agent.name} can't use {agent.model}: {exc}") from exc

    @classmethod
    def new(
        cls,
        topic: str,
        agents: Sequence[AgentSpec],
        make_provider: ProviderMaker,
        folder: Path | None = None,
        budget: float | None = None,
    ) -> "Room":
        if not topic.strip():
            raise RoomError("Give the room a topic: what the agents should talk about.")
        check_agents(agents)
        now = _now()
        info = RoomInfo(
            id=f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
            topic=topic.strip(),
            agents=list(agents),
            created_at=now,
            updated_at=now,
        )
        room = cls(info, make_provider, folder, budget)
        room.save()
        return room

    @property
    def id(self) -> str:
        return self.info.id

    def agent(self, name: str) -> AgentSpec:
        for agent in self.info.agents:
            if agent.name.lower() == name.lower():
                return agent
        raise RoomError(f"No agent in this room is called {name}.")

    def next_speaker(self) -> AgentSpec:
        """Whoever the last line mentions, other than its own speaker; or else whoever has
        waited longest since they last spoke (first in the room's order among those who
        haven't spoken), so a mention never leaves anyone out for long."""
        agents = self.info.agents
        lines = self.info.lines
        if lines:
            last = lines[-1]
            for mention in re.findall(r"@([A-Za-z][A-Za-z0-9_-]*)", last.text):
                for agent in agents:
                    if agent.name.lower() == mention.lower() and agent.name != last.speaker:
                        return agent
        spoke = {a.name: -1 for a in agents}  # the index of each agent's latest line
        for index, line in enumerate(lines):
            if line.speaker in spoke:
                spoke[line.speaker] = index
        waiting = [a for a in agents if not lines or a.name != lines[-1].speaker] or agents
        return min(waiting, key=lambda a: spoke[a.name])  # min keeps the first of equals

    def system_for(self, agent: AgentSpec) -> str:
        others = [
            f"- {a.name} ({a.model})" + (f": {a.persona}" if a.persona else "")
            for a in self.info.agents
            if a.name != agent.name
        ]
        others.append(f"- {USER}: the person who opened the room, who may join in")
        who = f", {agent.persona}" if agent.persona else ""
        return (
            f"You are {agent.name}{who}. You're one of several AI agents in a group "
            f"conversation, running on {agent.model}.\n\n"
            f"The topic: {self.info.topic}\n\n"
            "Also in the room:\n" + "\n".join(others) + "\n\n"
            'Each message from someone else is shown as "[Name]: text". Your own earlier '
            "messages are your turns.\n\n"
            "How to take part:\n"
            "- Write only your own next message. Don't put your name in front of it, and "
            "don't write lines for anyone else.\n"
            "- Keep it short, a few sentences as in a group chat, unless the topic needs "
            "more.\n"
            "- Respond to what the others actually said: build on it, question it, or "
            "disagree. Don't repeat it back.\n"
            "- To hand the floor to someone, mention them as @Name."
        )

    def messages_for(self, agent: AgentSpec) -> list[Message]:
        """The conversation from `agent`'s side. It starts with the topic, as every API wants
        a user message first, and ends with one, so it's the agent's turn to answer."""
        messages = [Message(role="user", content=[TextBlock(text=f"Topic: {self.info.topic}")])]
        for line in self.info.lines:
            mine = line.speaker == agent.name
            text = line.text if mine else f"[{line.speaker}]: {line.text}"
            if line.cut:
                text += " [cut off]"
            role: Literal["user", "assistant"] = "assistant" if mine else "user"
            if messages[-1].role == role:  # one message per side, which every API accepts
                messages[-1].content.append(TextBlock(text=text))
            else:
                messages.append(Message(role=role, content=[TextBlock(text=text)]))
        if messages[-1].role == "assistant":
            messages.append(Message(role="user", content=[TextBlock(text="(Your turn again.)")]))
        return messages

    def say(self, text: str) -> LineAdded:
        """Add the user's line."""
        if not text.strip():
            raise RoomError("There's nothing to say.")
        line = Line(speaker=USER, text=text.strip())
        self.info.lines.append(line)
        self.save()
        return LineAdded(line=line, dollars=self.info.dollars)

    async def speak(self, agent: AgentSpec) -> AsyncIterator[RoomEvent]:
        """One agent's turn: its reply as it streams in, then the line it added. If the turn
        is cancelled partway, what it had said is kept, marked as cut off. Raises
        ProviderError."""
        provider = self.providers[agent.name]
        yield SpeakerStarted(speaker=agent.name, model=agent.model)
        cleaner = _Cleaner(agent.name, [a.name for a in self.info.agents if a != agent] + [USER])
        response: ModelResponse | None = None
        try:
            async for item in provider.stream(self.system_for(agent), self.messages_for(agent), []):
                if isinstance(item, TextDelta):
                    piece = cleaner.feed(item.text)
                    if piece:
                        yield SpeakerText(speaker=agent.name, text=piece)
                elif isinstance(item, ModelResponse):
                    response = item
        except BaseException:  # cancelled (or failed) mid-reply: keep what was seen
            if cleaner.text.strip():
                self._add(
                    Line(speaker=agent.name, text=cleaner.text.strip(), model=agent.model, cut=True)
                )
            raise
        if response is None:
            raise ProviderError(f"{agent.model} ended without a reply.")
        full = "".join(b.text for b in response.content if isinstance(b, TextBlock))
        text = _clean(full, agent.name, cleaner.others).strip() or "(says nothing)"
        dollars = cost(response.usage_event())
        if dollars is None:
            model = response.model or agent.model
            if model not in self.info.unpriced:
                self.info.unpriced.append(model)
        else:
            self.info.dollars += dollars
        line = Line(
            speaker=agent.name, text=text, model=response.model or agent.model, dollars=dollars
        )
        self._add(line)
        yield LineAdded(line=line, dollars=self.info.dollars)

    async def run(self, turns: int) -> AsyncIterator[RoomEvent]:
        """Let agents speak, one at a time, for up to `turns` turns. Ends with RoomStopped,
        unless it's cancelled, which ends it with no event."""
        for _ in range(turns):
            budget = self.info.budget
            if budget is not None and self.info.dollars >= budget:
                yield RoomStopped(
                    reason="budget",
                    detail=f"The room has spent ${self.info.dollars:.4f} of its "
                    f"${budget:.2f} budget.",
                )
                return
            agent = self.next_speaker()
            try:
                async for event in self.speak(agent):
                    yield event
            except ProviderError as exc:
                yield RoomStopped(reason="error", detail=f"{agent.name} ({agent.model}): {exc}")
                return
        yield RoomStopped(reason="turns")

    def _add(self, line: Line) -> None:
        self.info.lines.append(line)
        self.save()

    def save(self) -> None:
        if self.folder is None:
            return
        self.info.updated_at = _now()
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{self.info.id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(self.info.model_dump_json(indent=1), encoding="utf-8")
        temporary.replace(path)  # never a half-written room

    async def aclose(self) -> None:
        for provider in self.providers.values():
            await provider.aclose()


def load_room(folder: Path, room_id: str) -> RoomInfo:
    """A saved room, by its id or the start of it. Raises RoomError."""
    if not re.fullmatch(r"[0-9A-Za-z-]+", room_id):
        raise RoomError(f"No room has the id {room_id!r}.")
    found = sorted(folder.glob(f"{room_id}*.json")) if folder.is_dir() else []
    if not found:
        raise RoomError(f"No room has the id {room_id!r}.")
    if len(found) > 1:
        raise RoomError(f"More than one room starts with {room_id!r}; give more of its id.")
    try:
        return RoomInfo.model_validate_json(found[0].read_bytes())
    except (OSError, ValidationError) as exc:
        raise RoomError(f"Room {found[0].stem} couldn't be read: {exc}") from exc


def recent_rooms(folder: Path, limit: int = 50) -> list[RoomInfo]:
    """Saved rooms, the most recently changed first. Ones that can't be read are skipped."""
    rooms: list[RoomInfo] = []
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            rooms.append(RoomInfo.model_validate_json(path.read_bytes()))
        except (OSError, ValidationError):
            continue
    rooms.sort(key=lambda r: r.updated_at, reverse=True)
    return rooms[:limit]


def router_maker(config: Config, env: Mapping[str, str]) -> ProviderMaker:
    """Makes each agent a ModelRouter of its own, so agents on one provider don't share a
    current model."""
    return lambda model: ModelRouter(config, env, canonical(model))


class _Cleaner:
    """Takes the speaker's own name off the start of a streamed reply, and stops at a line
    that starts speaking for someone else, as models used to transcripts sometimes do."""

    def __init__(self, name: str, others: Sequence[str]) -> None:
        self.name = name
        self.others = list(others)
        self.raw = ""
        self.text = ""  # what's been passed on
        self.done = False

    def feed(self, piece: str) -> str:
        if self.done:
            return ""
        self.raw += piece
        # Hold back a possible name at the start, and the last line, which may turn out to
        # be someone else's, until it's long enough to tell.
        if len(self.raw.strip()) < len(self.name) + 4 and "\n" not in self.raw.strip():
            return ""
        cleaned = _clean(self.raw, self.name, self.others)
        if len(cleaned) < len(_strip_own(self.raw, self.name)):
            self.done = True  # someone else's line began
        safe = cleaned if self.done else cleaned[: _held_back(cleaned)]
        new = safe[len(self.text) :] if safe.startswith(self.text) else ""
        self.text += new
        return new


def _strip_own(text: str, name: str) -> str:
    return re.sub(rf"^\s*\[?{re.escape(name)}\]?\s*:\s*", "", text, flags=re.IGNORECASE)


def _clean(text: str, name: str, others: Sequence[str]) -> str:
    text = _strip_own(text, name)
    if others:
        names = "|".join(re.escape(n) for n in [*others, name])
        found = re.search(rf"\n\s*\[?(?:{names})\]?\s*:", text, flags=re.IGNORECASE)
        if found:
            text = text[: found.start()]
    return text


def _held_back(text: str) -> int:
    """Where the text is safe to show up to: all but a last line short enough to still turn
    into "[Name]:", and the line break before it."""
    start = text.rfind("\n") + 1
    if start and len(text) - start <= MAX_NAME_TAG:
        return start - 1
    return len(text)


MAX_NAME_TAG = 28  # "[" + a name of up to 24 + "]:" and a little room


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
