"""Backups of the data file.

`create_backup` copies the file into a backup folder under a timestamped name.
`restore_backup` puts a backup back in place of the data file, after checking that it
really is a shopdesk file this release can open, so a bad restore can't leave the shop
unusable.
"""

import shutil
from pathlib import Path

from shopdesk.clock import Clock
from shopdesk.errors import StoreError
from shopdesk.store.codec import decode
from shopdesk.store.jsonstore import read_document, write_document
from shopdesk.store.migrations import upgrade

READABLE_VERSIONS = (1, 2)


def create_backup(data_file: Path, folder: Path, clock: Clock) -> Path:
    data_file = Path(data_file)
    if not data_file.exists():
        raise StoreError(f"There is no {data_file} to back up yet.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = clock().replace("-", "").replace(":", "").rstrip("Z")
    target = folder / f"{data_file.stem}-{stamp}.json"
    counter = 1
    while target.exists():
        counter += 1
        target = folder / f"{data_file.stem}-{stamp}-{counter}.json"
    shutil.copyfile(data_file, target)
    return target


def list_backups(folder: Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.json"))


def check_backup(backup: Path) -> dict:
    """The backup's document, if it can be restored."""
    raw = read_document(Path(backup))
    if raw.get("format") != "shopdesk":
        raise StoreError(f"{backup} is not a shopdesk backup.")
    if raw.get("version") not in READABLE_VERSIONS:
        raise StoreError(f"{backup} is version {raw.get('version')!r}, which can't be restored.")
    decode(upgrade(raw))
    return raw


def restore_backup(backup: Path, data_file: Path) -> None:
    raw = check_backup(backup)
    write_document(Path(data_file), raw)
