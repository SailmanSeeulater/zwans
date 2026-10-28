import csv
import io
from pathlib import Path

import pytest
from libsys.config import BranchDirectory, load_branches
from libsys.store import LibraryStore

REPO = Path(__file__).resolve().parents[1]
HEADER = "event,branch,loan_no,member,barcode,title,at"


@pytest.fixture
def branches() -> BranchDirectory:
    return load_branches(REPO / "branches.toml")


@pytest.fixture
def store() -> LibraryStore:
    return LibraryStore()


def rows(text: str) -> list[dict[str, str]]:
    """Export rows from CSV text; the header is added if it's missing."""
    text = text.strip()
    if not text.startswith("event"):
        text = HEADER + "\n" + text
    return list(csv.DictReader(io.StringIO(text)))


def write_export(folder: Path, text: str, name: str = "export.csv") -> Path:
    text = text.strip()
    if not text.startswith("event"):
        text = HEADER + "\n" + text
    path = folder / name
    path.write_text(text + "\n", encoding="utf-8")
    return path
