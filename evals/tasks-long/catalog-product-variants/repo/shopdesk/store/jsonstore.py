"""The data file: one JSON document per shop.

    {"format": "shopdesk", "version": 2, "saved_at": "...", "products": [...], ...}

Saving writes a temporary file next to the real one and renames it over, so a crash
never leaves half a file. Opening a missing file gives an empty shop.
"""

import json
import os
from pathlib import Path

from shopdesk.clock import Clock
from shopdesk.errors import StoreError
from shopdesk.models import ShopData
from shopdesk.store.codec import decode, encode
from shopdesk.store.migrations import FORMAT_VERSION, upgrade


def read_document(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoreError(f"{path} is not valid JSON: {exc}") from None
    except OSError as exc:
        raise StoreError(f"Can't read {path}: {exc}") from None
    if not isinstance(raw, dict):
        raise StoreError(f"{path} is not a shopdesk data file.")
    return raw


def write_document(path: Path, document: dict) -> None:
    text = json.dumps(document, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise StoreError(f"Can't write {path}: {exc}") from None


class JsonStore:
    def __init__(self, path: str | Path, clock: Clock) -> None:
        self.path = Path(path)
        self._clock = clock

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> ShopData:
        if not self.path.exists():
            return ShopData()
        return decode(upgrade(read_document(self.path)))

    def save(self, data: ShopData) -> None:
        document = {"format": "shopdesk", "version": FORMAT_VERSION, "saved_at": self._clock()}
        document.update(encode(data))
        write_document(self.path, document)
