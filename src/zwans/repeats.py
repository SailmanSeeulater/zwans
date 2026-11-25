"""Noticing a model that repeats itself: the same tool call, made again in one turn, coming
back with the same result, with nothing changed in between.

A local model that has finished sometimes doesn't end its turn. It writes its summary, then
runs the tests again, looks at the changes again, writes the summary again, and so on until
the turn's step limit. Each repeat costs a model call and tells it nothing new.

So the loop (loop.py) shows each call's result here. A repeat still runs, since the call is
cheap and its result is what the model asked for, but the result says it was a repeat. A
turn that keeps repeating after being told ends with stop_reason "repeating" rather than
at the step limit.

A call that changes something (a tool that isn't read-only, and isn't itself a repeat) wipes
the slate: after an edit, running the tests again is how the model learns whether it worked.
Numbers are left out when comparing results, so a test run that took 0.02s rather than
0.01s is still the same result.
"""

import json
import re
from typing import Any

from zwans.messages import ToolUseBlock

NOTE = (
    "\n\n[Zwans: you already made this exact call in this turn and got the same result, with "
    "nothing changed since, so it told you nothing new. If the work is done, stop calling "
    "tools and give your final answer. If it isn't, try something different.]"
)
NUMBERS = re.compile(r"\d+(?:\.\d+)?")


class Repeats:
    """The calls made so far in one turn, and how many came back the same as before."""

    def __init__(self) -> None:
        self.seen: dict[str, str] = {}  # a call, as name and input: its result's shape
        self.count = 0

    def observe(self, call: ToolUseBlock, content: str, is_error: bool, read_only: bool) -> bool:
        """Note this call and its result. Returns whether it repeated an earlier one."""
        key = _key(call.name, call.input)
        shape = f"{is_error}:{NUMBERS.sub('#', content)}"
        if self.seen.get(key) == shape:
            self.count += 1
            return True
        if not read_only:
            self.seen.clear()  # something may have changed: earlier calls could differ now
        self.seen[key] = shape
        return False


def _key(name: str, args: dict[str, Any]) -> str:
    return f"{name} {json.dumps(args, sort_keys=True, default=str)}"
