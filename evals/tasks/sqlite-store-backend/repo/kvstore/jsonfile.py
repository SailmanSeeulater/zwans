import json
import os
from pathlib import Path

from kvstore.base import KeyNotFound, Store


class JsonFileStore(Store):
    """Keeps everything in one JSON object on disk, rewritten after every change."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        if self._path.exists():
            self._data: dict[str, str] = json.loads(self._path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def _save(self) -> None:
        # Write a temporary file and move it into place, so a crash never leaves half a file.
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self._path)

    def _get(self, key: str) -> str:
        try:
            return self._data[key]
        except KeyError:
            raise KeyNotFound(key) from None

    def _set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._save()

    def _delete(self, key: str) -> None:
        try:
            del self._data[key]
        except KeyError:
            raise KeyNotFound(key) from None
        self._save()

    def _keys(self, prefix: str) -> list[str]:
        return [key for key in self._data if key.startswith(prefix)]
