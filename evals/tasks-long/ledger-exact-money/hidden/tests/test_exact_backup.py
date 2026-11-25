"""Rule 7: backups keep the data file as saved, the manifest's balances are strings, and
restoring checks them exactly; 2.x backups still restore."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from conftest import DATA, exact

from billfold import BackupError, Book, FixedClock
from billfold.backup import create_backup, read_backup, restore_backup


def members(archive: Path) -> dict[str, bytes]:
    with tarfile.open(archive, "r:gz") as src:
        return {m.name: src.extractfile(m).read() for m in src.getmembers()}


def pack(target: Path, files: dict[str, bytes]) -> Path:
    with tarfile.open(target, "w:gz") as dst:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))
    return target


def test_manifest_balances_are_strings(pennies: Book, tmp_path: Path) -> None:
    archive = create_backup(pennies, tmp_path)
    manifest, doc = read_backup(archive)
    balances = {info["name"]: info["balance"] for info in manifest["accounts"].values()}
    assert balances == {"Checking": "1214.97", "Yen": "13800"}


def test_backup_holds_the_data_file_as_saved(pennies: Book, tmp_path: Path) -> None:
    archive = create_backup(pennies, tmp_path)
    _, doc = read_backup(archive)
    saved = json.loads(pennies.save(tmp_path / "book.json").read_text("utf-8"))
    assert doc["version"] == saved["version"] == 3
    assert doc["transactions"] == saved["transactions"]
    assert doc["accounts"] == saved["accounts"]


def test_restore_round_trips_exactly(pennies: Book, tmp_path: Path) -> None:
    pennies.add_transaction("Checking", "2026-03-06", "-0.01")
    archive = create_backup(pennies, tmp_path)
    restored = restore_backup(archive, tmp_path / "restored.json", clock=FixedClock("2026-03-01"))
    exact(restored.balance("Checking"), "1214.96")
    reopened = Book.open(tmp_path / "restored.json")
    exact(reopened.balance("Checking"), "1214.96")
    exact(reopened.balance("Yen"), "13800")
    assert [str(t.amount) for t in reopened.transactions_for("Checking")][-1] == "-0.01"


def test_restore_compares_balances_exactly(pennies: Book, tmp_path: Path) -> None:
    archive = create_backup(pennies, tmp_path)
    files = members(archive)
    manifest = json.loads(files["manifest.json"])
    for info in manifest["accounts"].values():
        if info["name"] == "Yen":
            info["balance"] = "13801"
    files["manifest.json"] = json.dumps(manifest).encode()
    with pytest.raises(BackupError):
        restore_backup(pack(tmp_path / "bad.tar.gz", files), tmp_path / "restored.json")
    assert not (tmp_path / "restored.json").exists()


def old_backup(tmp_path: Path) -> Path:
    """A backup as billfold 2.x made them: a version 2 file and float balances."""
    payload = (DATA / "billfold-v2-floats.json").read_bytes()
    manifest = {
        "created": "2026-01-31T20:00:00Z",
        "version": 2,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "accounts": {
            "acc-1": {"name": "Checking", "currency": "EUR", "balance": 1281.04,
                      "transactions": 5},
            "acc-2": {"name": "Yen", "currency": "JPY", "balance": 13800.0, "transactions": 1},
            "acc-3": {"name": "Card", "currency": "EUR", "balance": -0.3, "transactions": 2},
        },
    }
    return pack(tmp_path / "billfold-20260131-200000.tar.gz",
                {"book.json": payload, "manifest.json": json.dumps(manifest).encode()})


def test_old_backups_still_restore(tmp_path: Path) -> None:
    restored = restore_backup(old_backup(tmp_path), tmp_path / "restored.json",
                              clock=FixedClock("2026-03-01"))
    exact(restored.balance("Card"), "-0.30")
    exact(restored.balance("Checking"), "1281.04")
    doc = json.loads((tmp_path / "restored.json").read_text("utf-8"))
    assert doc["version"] == 3
    reopened = Book.open(tmp_path / "restored.json")
    exact(reopened.balance("Yen"), "13800")
    exact(reopened.budgets.get("Subscriptions", "2026-01").amount, "19.99")
