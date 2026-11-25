import json
import zipfile
from datetime import datetime

import pytest
from clinicbook import BackupError, ClinicBook, Store
from support import visit, wall


def test_a_backup_restores_everything(book, clock, tmp_path):
    visit(book, datetime(2026, 1, 12, 9, 0))
    visit(book, datetime(2026, 1, 13, 9, 0), patient="P0002")
    path = book.backup(tmp_path / "backups" / "monday.zip")

    other = ClinicBook(Store.memory(), clock=clock)
    other.restore(path)

    assert [wall(a.start) for a in other.appointments()] == ["2026-01-12 09:00",
                                                             "2026-01-13 09:00"]
    assert other.history("store")[-1].action == "restored"
    with pytest.raises(Exception, match="clashes"):
        visit(other, datetime(2026, 1, 12, 9, 0), patient="P0003", room="C2")


def test_the_manifest_describes_the_backup(book, tmp_path):
    visit(book, datetime(2026, 1, 12, 9, 0))
    path = book.backup(tmp_path / "b.zip")

    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        data = json.loads(archive.read("store.json"))

    assert manifest["format"] == 1
    assert manifest["store_version"] == data["version"]
    assert manifest["counts"]["appointments"] == 1
    assert manifest["counts"]["patients"] == 3


def test_an_incomplete_backup_is_refused(book, clock, tmp_path):
    visit(book, datetime(2026, 1, 12, 9, 0))
    path = book.backup(tmp_path / "b.zip")
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        data = json.loads(archive.read("store.json"))
    data["appointments"] = []
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("store.json", json.dumps(data))

    other = ClinicBook(Store.memory(), clock=clock)
    with pytest.raises(BackupError, match="incomplete"):
        other.restore(broken)
    with pytest.raises(BackupError):
        other.restore(tmp_path / "missing.zip")
    assert other.appointments() == []
