"""Keeping a helpdesk in a JSON file.

The file is ``{"format": "deskline", "version": 3, "data": {...}}``. It is rewritten
atomically (temp file + rename) after every committed transaction.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..errors import StoreError
from .base import Store
from .migrate import CURRENT_VERSION, upgrade


def load(path: Path) -> Store:
    try:
        document = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        raise StoreError(f"no helpdesk file at {path}") from None
    except json.JSONDecodeError as exc:
        raise StoreError(f"{path} is not valid JSON: {exc}") from None
    store = Store.from_data(upgrade(document))
    attach(store, path)
    return store


def save(store: Store, path: Path) -> None:
    document = {"format": "deskline", "version": CURRENT_VERSION, "data": store.to_data()}
    text = json.dumps(document, indent=1, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def attach(store: Store, path: Path) -> None:
    store.on_commit = lambda s: save(s, path)


def create(path: Path) -> Store:
    if path.exists():
        raise StoreError(f"{path} already exists")
    store = Store()
    save(store, path)
    attach(store, path)
    return store
