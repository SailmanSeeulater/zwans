"""Agent types: subagents defined once, by name, for the Task tool to start.

An agent type is a Markdown file in ~/.zwans/agents/, or in a project's .zwans/agents/ or
.claude/agents/ (where Claude Code keeps its subagents, so those work too). A few come with
Zwans, in src/zwans/agents/:

    ---
    name: reviewer
    description: Reviews a change for bugs. Use after editing, before saying it's done.
    model: claude-haiku-5-5
    tools: Read, Glob, Grep, History
    max_steps: 20
    ---
    (its instructions)

The name is the file's unless the front matter gives one. Only the description is needed:
without one the model couldn't know when to use it. `model` is the model it runs on (left
out, or "inherit", for the session's subagent model; Claude Code's "haiku", "sonnet" and
"opus" stand for the latest of each); `tools` the tools it may use, of the session's (left
out for all of them); `max_steps` how many model calls it gets. The rest of the file is its
instructions, given to it on top of the session's prompt.

The model sees each type's name and description in the Task tool's description and starts
one with Task(agent="reviewer", ...), so a cheap, read-only reviewer is the same every time
rather than whatever the model thought to ask for that day.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from zwans.ext.skills import split_front_matter

# The agent types that come with Zwans, such as explore.
BUILTIN = Path(__file__).resolve().parent.parent / "agents"
# Claude Code's names for its models, as its agent files use them.
MODEL_ALIASES = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}
NAME = re.compile(r"^[A-Za-z0-9][\w.-]{0,63}$")


@dataclass(frozen=True)
class AgentType:
    name: str
    description: str
    instructions: str
    path: Path
    model: str | None = None  # None: the session's subagent model
    tools: tuple[str, ...] | None = None  # None: all the session's
    max_steps: int | None = None  # None: subagent_max_steps


def find_agents(folders: list[Path]) -> list[AgentType]:
    """The agent types in these folders, by name. A later folder's type replaces an earlier
    one's with the same name, so a project's wins over the user's and the user's over the
    ones that come with Zwans."""
    found: dict[str, AgentType] = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for file in sorted(folder.glob("*.md")):
            agent = load_agent(file)
            if agent is not None:
                found[agent.name] = agent
    return sorted(found.values(), key=lambda agent: agent.name)


def agent_folders(workspace: Path, home: Path | None, builtin: bool = False) -> list[Path]:
    """Where to look, in order: a later folder's type replaces an earlier one's."""
    folders = [BUILTIN] if builtin else []
    if home is not None:
        folders.append(home / "agents")
    return [*folders, workspace / ".claude" / "agents", workspace / ".zwans" / "agents"]


def load_agent(file: Path) -> AgentType | None:
    """The agent type a file defines, or None when it can't be read or has no
    description."""
    try:
        text = file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    fields, body = split_front_matter(text)
    name = fields.get("name", "").strip() or file.stem
    description = fields.get("description", "").strip()
    if not description or not NAME.match(name):
        return None
    model = fields.get("model", "").strip()
    model = MODEL_ALIASES.get(model.lower(), model)
    tools = [t.strip() for t in re.split(r"[,\s]+", fields.get("tools", "")) if t.strip()]
    steps = fields.get("max_steps", "").strip()
    return AgentType(
        name=name,
        description=description,
        instructions=body.strip(),
        path=file.resolve(),
        model=None if model.lower() in ("", "inherit") else model,
        tools=tuple(tools) if tools else None,
        max_steps=int(steps) if steps.isdigit() and int(steps) > 0 else None,
    )
