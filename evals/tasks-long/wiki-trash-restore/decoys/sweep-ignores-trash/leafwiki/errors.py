"""Exceptions raised by leafwiki.

Everything leafwiki raises on purpose derives from :class:`WikiError`, so callers (the CLI
in particular) can catch one type and show the message.
"""


class WikiError(Exception):
    """Base class for every error leafwiki raises on purpose."""


class PageNotFound(WikiError, LookupError):
    def __init__(self, title: str) -> None:
        super().__init__(f"no page called {title!r}")
        self.title = title


class PageExists(WikiError):
    def __init__(self, title: str) -> None:
        super().__init__(f"a page called {title!r} already exists")
        self.title = title


class InvalidTitle(WikiError, ValueError):
    pass


class RevisionNotFound(WikiError, LookupError):
    def __init__(self, title: str, number: int) -> None:
        super().__init__(f"{title!r} has no revision {number}")
        self.title = title
        self.number = number


class AttachmentNotFound(WikiError, LookupError):
    def __init__(self, title: str, name: str) -> None:
        super().__init__(f"{title!r} has no attachment {name!r}")
        self.title = title
        self.name = name


class AttachmentTooLarge(WikiError, ValueError):
    pass


class CommentNotFound(WikiError, LookupError):
    def __init__(self, comment_id: str) -> None:
        super().__init__(f"no comment {comment_id!r}")
        self.comment_id = comment_id


class TrashEntryNotFound(WikiError, LookupError):
    def __init__(self, entry_id: str) -> None:
        super().__init__(f"nothing in the trash with id {entry_id!r}")
        self.entry_id = entry_id


class InvalidSetting(WikiError, ValueError):
    pass


class StoreError(WikiError):
    """The wiki's folder is missing, damaged, or from a newer leafwiki."""


class QueryError(WikiError, ValueError):
    pass
