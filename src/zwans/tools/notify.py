"""The Notify tool: a desktop notification, for when someone asked to be told.

A long task, such as a full test run, a migration or a big refactor, is something people
leave running while they do something else. This shows a notification on their desktop
(Notification Center on macOS, notify-send on Linux) so they know it's done without
watching the terminal.

The text reaches the system as program arguments, never as part of a script, so nothing in
a message can run as AppleScript or shell. It runs the program directly, outside the
sandbox, since the sandbox can't reach the notification service.
"""

import shutil

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.ports import run_program

TIMEOUT = 15.0
# The message and the title come in as arguments after "--", so they're never AppleScript
APPLESCRIPT = [
    "-e",
    "on run argv",
    "-e",
    "display notification (item 1 of argv) with title (item 2 of argv)",
    "-e",
    "end run",
]


class NotifyInput(BaseModel):
    message: str = Field(
        min_length=1, max_length=200, description="What to say, in a sentence: what finished."
    )
    title: str = Field(
        default="Zwans", min_length=1, max_length=60, description="The notification's title."
    )


class NotifyTool:
    name = "Notify"
    description = (
        "Show a desktop notification with a short message. Use it only when the user asked to "
        "be told when something is done, or at the end of a task that took a long time, so "
        "they know without watching the terminal. Not for progress updates."
    )
    input_model = NotifyInput
    read_only = True  # it changes nothing, so it never needs asking

    async def run(self, args: NotifyInput, ctx: ToolContext) -> ToolOutput:
        message = " ".join(args.message.split())
        title = " ".join(args.title.split()) or "Zwans"
        if not message:
            raise ToolError("message is empty.")
        osascript = shutil.which("osascript")
        notify_send = shutil.which("notify-send")
        if osascript:
            argv = [osascript, *APPLESCRIPT, "--", message, title]
        elif notify_send:
            argv = [notify_send, "--app-name=Zwans", "--", title, message]
        else:
            raise ToolError(
                "Desktop notifications aren't supported here: neither osascript (macOS) nor "
                "notify-send (Linux) is installed."
            )
        ran = await run_program(argv, None, TIMEOUT)
        if ran.exit_code != 0:
            said = (ran.stderr.strip() or f"exit code {ran.exit_code}")[:300]
            raise ToolError(f"The notification couldn't be shown: {said}")
        return ToolOutput(content=f"Notified: {title}: {message}")


def available() -> bool:
    return shutil.which("osascript") is not None or shutil.which("notify-send") is not None
