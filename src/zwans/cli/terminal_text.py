"""Makes text from the model, a command or a workspace file safe to print. Escape codes in it
could move the cursor, erase lines or hide text, and so hide part of a change the user is
asked to allow."""

import re

COLOURS = re.compile(r"\x1b\[[0-9;]*m")
# Control characters other than tab and newline, and the bidirectional overrides that can
# make a line read differently from what it holds.
UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")


def printable(text: str) -> str:
    """The text without colour codes, and with any other control character shown as an
    escape (such as \\x1b), so it prints as what it is rather than acting on the terminal.
    A Windows line ending is just a line ending; only a lone carriage return is escaped."""
    return UNSAFE.sub(_escape, COLOURS.sub("", text.replace("\r\n", "\n")))


def _escape(match: re.Match[str]) -> str:
    code = ord(match.group())
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"
