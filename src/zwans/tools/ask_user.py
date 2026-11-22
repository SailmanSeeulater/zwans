"""The AskUser tool: put a question to the person, and wait for the answer.

Without it a model that isn't sure either guesses or ends its turn with a question buried
in prose. With it the question stands out, the choices are one click or keystroke, and the
turn carries on with the answer.

How the question is shown is up to whoever is running the session: the web UI and the
terminal chat each give the session a way to ask. A run with nobody watching gives none,
and the model is told to decide for itself.
"""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolOutput

NOBODY = (
    "Nobody is here to answer in this run. Decide for yourself, choosing what's easiest to "
    "undo, and say in your final answer what you assumed."
)


class AskUserInput(BaseModel):
    question: str = Field(
        min_length=1,
        description="One question, short enough to answer at a glance. Give the context it "
        "needs in the question itself.",
    )
    options: list[str] = Field(
        default=[],
        max_length=4,
        description="Two to four answers to choose from, each a few words, your "
        "recommendation first. Leave it empty for an open question. The person can always "
        "type something else.",
    )


class AskUserTool:
    name = "AskUser"
    description = (
        "Ask the person a question and wait for their answer. Use it when a choice is "
        "theirs to make and guessing wrong would cost real work: which of two designs, "
        "whether to delete something, what an unclear request means. Don't ask what you can "
        "find out by reading the code, and don't ask for permission to do what was asked."
    )
    input_model = AskUserInput
    read_only = True  # it changes nothing, so the policy has nothing to judge

    async def run(self, args: AskUserInput, ctx: ToolContext) -> ToolOutput:
        if ctx.ask is None:
            return ToolOutput(content=NOBODY, is_error=True)
        options = [" ".join(option.split()) for option in args.options if option.strip()]
        answer = await ctx.ask(args.question.strip(), options)
        if answer is None or not answer.strip():
            return ToolOutput(content=NOBODY, is_error=True)
        return ToolOutput(content=f"The user answered: {answer.strip()}")
