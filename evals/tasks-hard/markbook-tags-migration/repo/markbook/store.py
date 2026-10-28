"""Reading and writing markbook files.

Loading migrates old formats in memory; the file itself is only rewritten (in the current
format) when something is saved. The first time a file in an older format is overwritten,
the original is kept next to it as <name>.v<old version>.bak.
"""

import json
import os
import shutil
from pathlib import Path

from .collection import Collection
from .migrations import migrate, version_of
from .schema import CURRENT_VERSION, validate


def read_document(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def load(path: Path | str) -> Collection:
    """The collection in path, or an empty one when the file does not exist yet."""
    path = Path(path)
    if not path.exists():
        return Collection()
    raw = read_document(path)
    doc = migrate(raw)
    validate(doc)
    collection = Collection.from_doc(doc)
    collection.loaded_version = version_of(raw)
    return collection


def backup_path(path: Path, version: int) -> Path:
    return path.with_name(f"{path.name}.v{version}.bak")


def save(collection: Collection, path: Path | str) -> None:
    path = Path(path)
    doc = collection.to_doc()
    validate(doc)
    old = collection.loaded_version
    if path.exists() and old is not None and old < CURRENT_VERSION:
        backup = backup_path(path, old)
        if not backup.exists():
            shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    collection.loaded_version = CURRENT_VERSION
