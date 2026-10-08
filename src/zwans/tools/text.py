"""Decode and re-encode files so edits keep the original encoding and line endings."""

import codecs
from dataclasses import dataclass
from typing import Self

from zwans.tools.base import ToolError


@dataclass(frozen=True)
class TextFile:
    text: str = ""  # always uses "\n" line endings
    encoding: str = "utf-8"
    newline: str = "\n"

    @classmethod
    def decode(cls, data: bytes) -> Self:
        encoding = "utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-8"
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            # Latin-1 maps every byte to a character, so files in unknown encodings round-trip.
            encoding = "latin-1"
            text = data.decode(encoding)
        newline = "\r\n" if "\r\n" in text else "\n"
        return cls(text.replace("\r\n", "\n"), encoding, newline)

    def encode(self, text: str) -> bytes:
        """Encode new contents for this file, using its encoding and line endings."""
        text = text.replace("\r\n", "\n").replace("\n", self.newline)
        try:
            return text.encode(self.encoding)
        except UnicodeEncodeError as exc:
            raise ToolError(f"The new text can't be saved as {self.encoding}.") from exc
