"""Backups: a .tar.gz holding the data file and a manifest.

The manifest records when the backup was made, the file version, a SHA-256 of book.json
and each account's balance and transaction count. Restoring checks all of it before
anything is written, so a damaged or hand-edited backup is refused instead of silently
giving you different numbers.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .clock import stamp
from .errors import BackupError, StorageError
from .storage import book_from_document, document_of
from .storage.jsonfile import write_document

if TYPE_CHECKING:
    from .book import Book

BOOK_NAME = "book.json"
MANIFEST_NAME = "manifest.json"


def _balances(book: Book) -> dict[str, dict]:
    return {
        account.id: {
            "name": account.name,
            "currency": account.currency,
            "balance": round(float(book.balance(account)), 2),
            "transactions": len(book.transactions_for(account)),
        }
        for account in book.accounts.values()
    }


def _add_file(archive: tarfile.TarFile, name: str, data: bytes, when: datetime) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(when.timestamp())
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(data))


def create_backup(book: Book, folder: Path | str) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    when = book.clock.now()
    doc = document_of(book)
    payload = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest = {
        "created": stamp(when),
        "version": doc["version"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "accounts": _balances(book),
    }
    target = folder / f"billfold-{when.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        _add_file(archive, BOOK_NAME, payload, when)
        _add_file(archive, MANIFEST_NAME, json.dumps(manifest, indent=2).encode(), when)
    return target


def _read_member(archive: tarfile.TarFile, name: str) -> bytes:
    try:
        member = archive.getmember(name)
    except KeyError:
        raise BackupError(f"backup has no {name}") from None
    handle = archive.extractfile(member)
    if handle is None:
        raise BackupError(f"{name} in the backup is not a file")
    return handle.read()


def read_backup(path: Path | str) -> tuple[dict, dict]:
    """(manifest, document) of a backup, after checking the checksum."""
    try:
        with tarfile.open(path, "r:gz") as archive:
            payload = _read_member(archive, BOOK_NAME)
            manifest = json.loads(_read_member(archive, MANIFEST_NAME))
    except (tarfile.TarError, OSError, json.JSONDecodeError) as error:
        raise BackupError(f"can't read backup {path}: {error}") from None
    if hashlib.sha256(payload).hexdigest() != manifest.get("sha256"):
        raise BackupError("backup is damaged: book.json doesn't match its checksum")
    return manifest, json.loads(payload)


def verify(manifest: dict, book: Book) -> None:
    expected = manifest.get("accounts", {})
    if set(expected) != set(book.accounts):
        raise BackupError("backup manifest lists different accounts than its data file")
    for account_id, info in expected.items():
        account = book.accounts[account_id]
        count = len(book.transactions_for(account))
        if count != info["transactions"]:
            raise BackupError(f"{account.name}: manifest says {info['transactions']} transactions, file has {count}")
        if abs(float(book.balance(account)) - float(info["balance"])) > 0.005:
            raise BackupError(f"{account.name}: balance doesn't match the manifest")


def restore_backup(path: Path | str, target: Path | str, *, clock=None) -> Book:
    """Check a backup and write its book to `target` (the old file is kept as .bak)."""
    manifest, doc = read_backup(path)
    try:
        book = book_from_document(doc, clock=clock, path=Path(target))
    except (StorageError, KeyError, ValueError) as error:
        raise BackupError(f"backup data can't be loaded: {error}") from None
    book.balances.drop()
    verify(manifest, book)
    write_document(Path(target), document_of(book))
    return book


def list_backups(folder: Path | str) -> list[Path]:
    return sorted(Path(folder).glob("billfold-*.tar.gz"))
