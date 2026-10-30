"""The Skill tool: load a skill's instructions, or another file from its folder."""

from pydantic import BaseModel, Field

from zwans.ext.skills import Skill
from zwans.tools.base import ToolContext, ToolError, ToolOutput


class SkillInput(BaseModel):
    name: str = Field(description="The skill's name, as listed in the system prompt.")
    file: str | None = Field(
        default=None,
        description="Another file from the skill's folder, when its instructions point to one.",
    )


class SkillTool:
    name = "Skill"
    description = (
        "Load a skill: instructions for a particular kind of task, listed by name and "
        "description in the system prompt. Load one when the task matches its description, "
        "before starting, and follow it. Its instructions may point to other files in the "
        "skill; load those by passing file."
    )
    input_model = SkillInput
    read_only = True

    def __init__(self, skills: list[Skill]) -> None:
        self.skills = {skill.name: skill for skill in skills}

    async def run(self, args: SkillInput, ctx: ToolContext) -> ToolOutput:
        skill = self.skills.get(args.name)
        if skill is None:
            known = ", ".join(sorted(self.skills)) or "none"
            raise ToolError(f"There's no skill called {args.name!r}. Skills: {known}.")
        if args.file is not None:
            return ToolOutput(content=skill.read(args.file))
        text = skill.instructions()
        others = skill.other_files()
        if others:
            listed = "\n".join(f"- {name}" for name in others)
            text += f"\n\nOther files in this skill, loaded by passing file:\n{listed}"
        return ToolOutput(content=text)
