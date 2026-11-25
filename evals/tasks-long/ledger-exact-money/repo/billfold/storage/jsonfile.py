"""The data file on disk: one JSON document, written atomically, previous copy kept."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..errors import StorageError


def read_document(path: Path) -> dict:
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        raise
    except OSError as error:
        raise StorageError(f"can't read {path}: {error}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise StorageError(f"{path} is not valid JSON: {error}") from None


def write_document(path: Path, doc: dict, keep_previous: bool = True) -> None:
    """Write next to the target and rename over it, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if keep_previous and path.exists():
            os.replace(path, path.with_suffix(path.suffix + ".bak"))
        os.replace(temp_name, path)
    except BaseException:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise
