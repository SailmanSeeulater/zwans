"""Exceptions raised by billfold. Everything derives from BillfoldError."""


class BillfoldError(Exception):
    """Base class: the CLI prints these as plain messages instead of tracebacks."""


class MoneyError(BillfoldError, ValueError):
    """An amount that can't be read or isn't allowed where it was given."""


class UnknownCurrency(BillfoldError, KeyError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:
        return f"unknown currency: {self.code}"


class NotFound(BillfoldError, LookupError):
    """No account, transaction, rule or entry by that name or id."""


class DuplicateName(BillfoldError):
    """Two accounts (or categories, or rules) can't share a name."""


class ValidationError(BillfoldError, ValueError):
    """A value that doesn't fit the model (bad date, unknown kind, empty name...)."""


class RateMissing(BillfoldError):
    """No exchange rate between two currencies on or before a date."""


class ImportProblem(BillfoldError):
    """A file being imported can't be read."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message if line is None else f"line {line}: {message}")
        self.line = line


class StatementMismatch(ImportProblem):
    """A bank statement whose entries don't add up to its closing balance."""


class StorageError(BillfoldError):
    """The data file can't be read or written."""


class BackupError(BillfoldError):
    """A backup archive is damaged, or doesn't match its manifest."""


class NothingToUndo(BillfoldError):
    pass
