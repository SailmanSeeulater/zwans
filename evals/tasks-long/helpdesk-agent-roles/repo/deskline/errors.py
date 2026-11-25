"""Errors raised by deskline.

Every error carries a short machine-readable ``code`` that the JSON API and the CLI use
when they report it.
"""


class DesklineError(Exception):
    code = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DesklineError):
    code = "not_found"

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"no {kind} {key!r}")
        self.kind = kind
        self.key = key


class ValidationError(DesklineError):
    code = "invalid"


class Conflict(DesklineError):
    code = "conflict"


class InvalidTransition(Conflict):
    def __init__(self, ticket_id: str, current: str, wanted: str) -> None:
        super().__init__(f"ticket {ticket_id} cannot go from {current} to {wanted}")
        self.current = current
        self.wanted = wanted


class StoreError(DesklineError):
    code = "store"


class TemplateError(DesklineError):
    code = "template"


class QueryError(ValidationError):
    pass


class MailError(ValidationError):
    pass
