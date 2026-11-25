"""Loading and saving books."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .jsonfile import read_document, write_document
from .migrations import CURRENT_VERSION, upgrade
from .serialize import book_to_dict, fill_book

if TYPE_CHECKING:
    from ..book import Book

__all__ = [
    "CURRENT_VERSION",
    "book_from_document",
    "document_of",
    "load_book",
    "save_book",
]


def document_of(book: Book) -> dict:
    return book_to_dict(book, CURRENT_VERSION)


def book_from_document(doc: dict, *, clock=None, path: Path | None = None) -> Book:
    from ..book import Book

    book = Book(clock=clock, path=path)
    return fill_book(book, upgrade(doc))


def load_book(path: Path, *, clock=None) -> Book:
    from ..book import Book

    try:
        doc = read_document(path)
    except FileNotFoundError:
        return Book(clock=clock, path=path)
    return book_from_document(doc, clock=clock, path=path)


def save_book(book: Book, path: Path) -> None:
    write_document(path, document_of(book))
