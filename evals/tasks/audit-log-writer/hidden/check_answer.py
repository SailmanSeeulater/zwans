"""Checks answer.txt holds the right answer and that the project's files were left alone."""

import hashlib
import sys
from pathlib import Path

root = Path(__file__).resolve().parent

# SHA-256 of every file the task started with, with CRLF read as LF so checkouts on any OS match.
UNCHANGED = {
    "accounts/__init__.py": "d31888a2c7444e1e4ec5bd53ad5828229132e70820b994ab98ed35f8c4cf077e",
    "accounts/audit.py": "414df12766eb8bcf7965185a2c5a69ee236a269f2035ef988ebf88a68c83fae7",
    "accounts/events.py": "51fdab347965a5f6cced257b7deead85e508185505d119f499f340ebf6c6e8f2",
    "accounts/handlers.py": "9332ee4e6612ccfd15df1352797517b3755c47a46b65650db54b966f460dc194",
    "accounts/mailer.py": "89dd3099d5b4c65ab95b4ac4e793b087f1f611aee8fe7e757819e7d86a75074d",
    "accounts/service.py": "d268d2e9e9e40447f55f2354023d9f64981c24bfdf3a8f43841e3ad5d8d355b4",
    "accounts/settings.py": "d4ec2098a3bb8f690fa269737580463226ab5a3dc875c172b99e92c72f40e667",
    "accounts/sinks.py": "e67590217344e72b52022c434160e970496fd0e76a0764f40ec0918b4d5a5766",
    "tests/test_service.py": "d25cc2133fa2f688945f2ea3253791d84c218c181cb3ac661d64b21f08182915",
}


def judge(answer: str) -> bool:
    """Right answer: RotatingFileSink._write_line (a module path in front is fine)."""
    name = answer.strip().strip("`'\"").strip().removesuffix("()")
    parts = name.replace("/", ".").replace(":", ".").split(".")
    return parts[-2:] == ["RotatingFileSink", "_write_line"]


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
