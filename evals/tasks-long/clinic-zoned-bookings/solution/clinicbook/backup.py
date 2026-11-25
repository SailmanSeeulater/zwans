"""Backups: a zip holding the data file and a manifest describing it."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import BackupError, StorageError
from .storage import VERSION, Store
from .timeutil import format_instant

FORMAT = 1
MANIFEST = "manifest.json"
DATA = "store.json"


def write_backup(store: Store, path: str | Path, now: datetime) -> Path:
    path = Path(path)
    data = store.to_dict()
    manifest = {
        "format": FORMAT,
        "store_version": data["version"],
        "taken_at": format_instant(now),
        "counts": store.counts(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
        archive.writestr(DATA, json.dumps(data, indent=2))
    return path


def read_manifest(path: str | Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read(MANIFEST))
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise BackupError(f"{path} is not a clinicbook backup: {exc}") from None


def read_backup(path: str | Path) -> Store:
    """The store a backup holds, after checking it is complete."""
    manifest = read_manifest(path)
    if manifest.get("format") != FORMAT:
        raise BackupError(f"unknown backup format {manifest.get('format')!r}")
    version = manifest.get("store_version")
    if not isinstance(version, int) or version > VERSION:
        raise BackupError(
            f"backup holds data version {manifest.get('store_version')}, "
            f"this clinicbook uses version {VERSION}"
        )
    try:
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read(DATA))
    except (KeyError, json.JSONDecodeError) as exc:
        raise BackupError(f"backup {path} is damaged: {exc}") from None
    for table, count in manifest.get("counts", {}).items():
        if len(data.get(table, [])) != count:
            raise BackupError(f"backup {path} is incomplete: {table} should have {count} rows")
    try:
        return Store.from_dict(data)
    except StorageError as exc:
        raise BackupError(f"backup {path} is damaged: {exc}") from None
