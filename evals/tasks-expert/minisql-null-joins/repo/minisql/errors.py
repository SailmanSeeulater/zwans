"""The one exception minisql raises for anything wrong with a statement."""


class SQLError(Exception):
    """A statement that can't be tokenized, parsed, planned or run."""
