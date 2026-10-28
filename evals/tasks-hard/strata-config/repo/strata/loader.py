"""Reading Strata configuration files. SPEC.md at the project root defines the format."""

import os
from collections.abc import Mapping
from pathlib import Path


class ConfigError(Exception):
    """A configuration that cannot be read. `file` and `line` say where, when known."""

    def __init__(self, message: str, file: Path | None = None, line: int | None = None):
        super().__init__(message)
        self.file = file
        self.line = line


def load(path: str | os.PathLike[str], env: Mapping[str, str] | None = None) -> dict:
    """Read the Strata configuration at `path` and everything it includes."""
    raise NotImplementedError
