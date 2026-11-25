"""Every error orbit raises on purpose is a CrmError, so callers can catch just that."""


class CrmError(Exception):
    pass


class NotFound(CrmError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"No {kind} {key!r}.")
        self.kind = kind
        self.key = key


class InvalidValue(CrmError):
    pass


class Conflict(CrmError):
    pass


class NothingToUndo(CrmError):
    def __init__(self) -> None:
        super().__init__("Nothing to undo.")


class StoreError(CrmError):
    pass


class ImportFailed(CrmError):
    pass
