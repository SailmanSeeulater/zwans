"""Plan mode: the model looks and proposes, and nothing changes until the user approves.

While it's on, the permissions work as in read-only mode, and allow rules (the user's, or
"always" answers) don't widen that, so a plan can't start being carried out by a rule
written for normal work. Each prompt carries a note asking for a plan instead of changes.
The note goes in the user's message rather than the system prompt, which stays the same for
the whole session so earlier turns stay cached, and it's left out wherever the prompt is
shown or put back in the composer.

Approving ("go") turns plan mode off and asks the model to carry the plan out. Turning it
off without approving tells the model once, with the next prompt, that it may change files
again, since its last instructions said it couldn't.
"""

TAG = "<plan-mode>"
END_TAG = "</plan-mode>"

PLANNING = f"""{TAG}
Zwans is in plan mode. Don't change anything yet: tools that change files, run code or use \
the network are refused until the user approves a plan. Use the reading tools to look at \
what the task needs, then reply with a plan:
- what you found that matters, in a sentence or two;
- the steps, numbered, each naming the files it changes;
- how you'll check it works;
- anything you need the user to decide.
Keep it short enough to read in a minute. If the request is a question rather than a task, \
just answer it.
{END_TAG}"""

ENDED = f"""{TAG}
Plan mode is off: you can change files and run commands again, as the permissions allow.
{END_TAG}"""

GO = "Go ahead with the plan."

GO_NOTE = f"""{TAG}
The user approved the plan, and plan mode is off. Carry it out now, step by step, and check \
it as the plan said. If something turns out different from what the plan assumed, adapt and \
say what changed.
{END_TAG}"""


def is_note(text: str) -> bool:
    """Whether a text block of a user's message is one of these notes, not what they wrote."""
    return text.startswith(TAG)
