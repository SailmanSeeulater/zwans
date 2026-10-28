"""Checks answer.txt holds the right answer and that the project's files were left alone."""

import hashlib
import sys
from pathlib import Path

root = Path(__file__).resolve().parent

# SHA-256 of every file the task started with, with CRLF read as LF so checkouts on any OS match.
UNCHANGED = {
    "fetcher/__init__.py": "d2b9907b7628e34905654d8f1a667e3a441ad5ee329a87fdd4896cc5da35f4c6",
    "fetcher/client.py": "5e25770f23fd926fd89fb9e2edcd72b47b996a3521ed3c2ca9264c2a37633946",
    "fetcher/config.py": "f5fe3327feed58c111fa468ac463daf4f7a8db353ebf3dd6b32c68579636b626",
    "fetcher/transport.py": "53f36c43d44ad28851d9b6590fb206455bc9f6d817675597edf60f51841e08d2",
    "tests/test_client.py": "bb38acd89a7804588f036e3f39424d983f558a7bce5f4ea4bcdd3316424444a2",
}


def judge(answer: str) -> bool:
    """Right answer: http.attempt_timeout=1.5 (seconds)."""
    text = "".join(answer.lower().replace("`", "").split())
    key, equals, value = text.partition("=")
    if not equals or key != "http.attempt_timeout":
        return False
    for unit in ("seconds", "second", "secs", "sec", "s"):
        value = value.removesuffix(unit)
    try:
        return float(value) == 1.5
    except ValueError:
        return False


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
