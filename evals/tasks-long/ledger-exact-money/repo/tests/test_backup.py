import io
import json
import tarfile
from pathlib import Path

import pytest

from billfold import BackupError, Book, FixedClock
from billfold.backup import create_backup, list_backups, read_backup, restore_backup


def test_backup_and_restore(household: Book, tmp_path: Path) -> None:
    archive = create_backup(household, tmp_path / "backups")
    assert archive.name.startswith("billfold-20260301-") and archive.name.endswith(".tar.gz")
    assert list_backups(tmp_path / "backups") == [archive]
    manifest, doc = read_backup(archive)
    assert manifest["accounts"]["acc-1"]["transactions"] == 4

    restored = restore_backup(archive, tmp_path / "restored.json", clock=FixedClock("2026-03-01"))
    assert restored.balance("Checking") == household.balance("Checking")
    reopened = Book.open(tmp_path / "restored.json")
    assert len(reopened.transactions) == 5


def _rewrite(archive: Path, target: Path, change) -> Path:
    with tarfile.open(archive, "r:gz") as src:
        files = {m.name: src.extractfile(m).read() for m in src.getmembers()}
    files = change(files)
    with tarfile.open(target, "w:gz") as dst:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))
    return target


def test_a_damaged_backup_is_refused(household: Book, tmp_path: Path) -> None:
    archive = create_backup(household, tmp_path)

    def tamper(files):
        files["book.json"] = files["book.json"].replace(b"REWE Markt", b"REWE Murkt")
        return files

    bad = _rewrite(archive, tmp_path / "bad.tar.gz", tamper)
    with pytest.raises(BackupError, match="checksum"):
        restore_backup(bad, tmp_path / "restored.json")
    assert not (tmp_path / "restored.json").exists()


def test_a_manifest_that_disagrees_is_refused(household: Book, tmp_path: Path) -> None:
    archive = create_backup(household, tmp_path)

    def tamper(files):
        manifest = json.loads(files["manifest.json"])
        manifest["accounts"]["acc-1"]["transactions"] = 3
        files["manifest.json"] = json.dumps(manifest).encode()
        return files

    bad = _rewrite(archive, tmp_path / "bad.tar.gz", tamper)
    with pytest.raises(BackupError):
        restore_backup(bad, tmp_path / "restored.json")
