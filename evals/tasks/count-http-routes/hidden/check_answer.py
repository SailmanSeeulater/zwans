"""Checks answer.txt holds the right answer and that the project's files were left alone."""

import hashlib
import sys
from pathlib import Path

root = Path(__file__).resolve().parent

# SHA-256 of every file the task started with, with CRLF read as LF so checkouts on any OS match.
UNCHANGED = {
    "tests/test_app.py": "faad7fcf4e006b3d931ec754308eb5bd41e0c3fffe2fe27bd1bdab59cf96cd30",
    "webapp/__init__.py": "1dd11ec6f56745752cc512505ef932864f51741f8df22220be92471f210f3246",
    "webapp/app.py": "fb08bddd835b2e007ffd37077dbe6e8ed59b662081a7b1d03db01e0f4f6fd7ac",
    "webapp/router.py": "8ce450cf72f85c836f06117bd15d8e20e14676b9141cbe2e6664e0efeb23246b",
    "webapp/settings.py": "39a17d7b65ec4c7636ef7b5f12d2c8ef3175ffe10695e466f2041be01d37fabd",
    "webapp/views/__init__.py": "6edb7cb70e5219a127472e41e3c84f5b9fa29d02e663da566a8ae9081e949bad",
    "webapp/views/admin.py": "e507e7b6e03679dcbfb3f4692f146b4f5014698c5121fd8a32d5014f30ce99fa",
    "webapp/views/legacy.py": "a931ee279bf11386dfd976112a8bb75728ee6f0c8f54fbb12409d7019233775f",
    "webapp/views/orders.py": "c933f24597d43faf7a3eb7ca1a7bb1f77c8783bb6976a87c4de2b11cf4c849ac",
    "webapp/views/users.py": "cd5e2697d9a1ba33caf31c40965ec8740306ef52968cbd1846a7a75a73d5f56e",
}


def judge(answer: str) -> bool:
    """Right answer: 22."""
    return answer.strip().strip("`").rstrip(".").strip() == "22"


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
