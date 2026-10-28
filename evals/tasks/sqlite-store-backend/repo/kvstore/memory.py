from kvstore.base import KeyNotFound, Store


class MemoryStore(Store):
    """Keeps everything in a dict. Gone when the process ends."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def _get(self, key: str) -> str:
        try:
            return self._data[key]
        except KeyError:
            raise KeyNotFound(key) from None

    def _set(self, key: str, value: str) -> None:
        self._data[key] = value

    def _delete(self, key: str) -> None:
        try:
            del self._data[key]
        except KeyError:
            raise KeyNotFound(key) from None

    def _keys(self, prefix: str) -> list[str]:
        return [key for key in self._data if key.startswith(prefix)]
