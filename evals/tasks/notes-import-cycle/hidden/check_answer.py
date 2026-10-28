"""Checks answer.txt holds the right answer and that the project's files were left alone."""

import hashlib
import sys
from pathlib import Path

root = Path(__file__).resolve().parent

# SHA-256 of every file the task started with, with CRLF read as LF so checkouts on any OS match.
UNCHANGED = {
    "notes/__init__.py": "af7d1377f057f52ba0ce3c7f575da63e1f46cecb74d9e29523e2f732dd42b53b",
    "notes/cli.py": "c5132159d7712dae5fae02e8558beaec1aa3e3590b364bfd189414cbb323f0eb",
    "notes/export.py": "2ddf6866e9e2c76f2d9a7842be8ffd35cfecedf94353472abf1f516c96f399b1",
    "notes/models.py": "588622b661df6379d5e501dd61dede3f48d71b3c6731bd9dd1cb1226f113d392",
    "notes/render.py": "9a6ee7dc541c6030a644d34951ef74a523e0bd56d8780f5bbc24ae7e9984e3cc",
    "notes/search.py": "02592995934bf92047dfcd9321c04a77bdd68a9e04f3d7f10fdb6f3c3108c367",
    "notes/storage.py": "12b4ef2c128221fa05d0e827dc30307df77228d69a6f94209196a97f84f2ade2",
    "notes/tags.py": "837609aa0d6b01284a423c98ff1e225de62321b0682d972c4c9d5bfd4c3d4edd",
    "notes/util.py": "1a272e473dd75c4c853c148f8ba5efb6583955ee3a328b60cff78a97030b8aa0",
    "tests/test_render.py": "bb2912b1fec270d3b9955bb558ed85db82f2d0bc74e21e1c4e743218ebee1f70",
}


def judge(answer: str) -> bool:
    """Right answer: notes.storage, notes.tags and notes.search, in any order."""
    names = set()
    for item in answer.replace(",", " ").replace("->", " ").replace("→", " ").split():
        name = item.strip("`'\"-*").removesuffix(".py").replace("/", ".").replace("\\", ".")
        if name:
            names.add(name if name.startswith("notes.") else f"notes.{name}")
    return names == {"notes.storage", "notes.tags", "notes.search"}


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


problems = []
for name, digest in UNCHANGED.items():
    path = root / name
    if not path.is_file():
        problems.append(f"{name} was deleted")
    elif fingerprint(path) != digest:
        problems.append(f"{name} was changed")

answer_file = root / "answer.txt"
if not answer_file.is_file():
    problems.append("answer.txt is missing")
else:
    answer = answer_file.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not judge(answer):
        problems.append(f"wrong answer: {answer!r}")

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
