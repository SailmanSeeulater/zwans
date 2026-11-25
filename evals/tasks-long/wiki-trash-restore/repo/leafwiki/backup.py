"""Backups: the whole wiki in one zip file, and back.

A backup holds ``backup.json`` (the store's dump: every record and every attachment) and
a short ``README.txt``. The search index isn't included; it is rebuilt when the restored
wiki is first opened.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .clock import Clock, stamp, system_clock
from .errors import StoreError
from .storage import DirStore

if TYPE_CHECKING:
    from .wiki import Wiki

DUMP_NAME = "backup.json"


def create_backup(wiki: Wiki, path: str | os.PathLike[str]) -> dict[str, int]:
    """Write a backup of ``wiki`` to ``path``. Returns how many of each thing it holds."""
    data = wiki.store.dump()
    data["created_at"] = stamp(wiki.clock())
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(DUMP_NAME, json.dumps(data, ensure_ascii=False))
        archive.writestr(
            "README.txt",
            f"leafwiki backup of {wiki.settings.site_name}, made {data['created_at']}.\n"
            "Restore it with: leafwiki unpack-backup <this file> <new folder>\n",
        )
    return summarise(data)


def read_backup(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read(DUMP_NAME).decode("utf-8"))
    except (KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise StoreError(f"{path} is not a leafwiki backup ({error})") from None


def summarise(data: dict[str, Any]) -> dict[str, int]:
    return {
        "pages": len(data.get("pages", [])),
        "attachments": len(data.get("blobs", {})),
        "comments": sum(len(c) for c in data.get("comments", {}).values()),
        "changes": len(data.get("changes", [])),
    }


def restore_backup(
    path: str | os.PathLike[str],
    target: str | os.PathLike[str],
    clock: Clock | None = None,
) -> Wiki:
    """Unpack a backup into a new folder and open the wiki there."""
    from .wiki import Wiki

    data = read_backup(path)
    folder = Path(target)
    if folder.exists() and any(folder.iterdir()):
        raise StoreError(f"{folder} is not empty")
    store = DirStore(folder, create=True)
    store.write_meta({})
    store.load_dump(data)
    return Wiki(store, clock=clock or system_clock)
