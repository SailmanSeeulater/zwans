"""Checks answer.txt holds the right answer and that the project's files were left alone."""

import hashlib
import sys
from pathlib import Path

root = Path(__file__).resolve().parent

# SHA-256 of every file the task started with, with CRLF read as LF so checkouts on any OS match.
UNCHANGED = {
    "checkout/__init__.py": "a38dff64275eba164dd81b63a0751920b9dabd33c479f7f4c58d9a7c9cbe88ae",
    "checkout/catalog.py": "aef4105e5b0b9429fcfd8fb7d30490ab960c8bde80cbe928d7f2581d3bddee83",
    "checkout/discounts.py": "c6647d24d4be3d0bb7d564caac60f4eda30ec116924baa7e1b78e391d0cd6f52",
    "checkout/pricing.py": "b11306d08733e0036e5aad676f28922f5f3623d8fe1021c525e9a67e6229d9ee",
    "checkout/quote.py": "1b1fb50b0412ceeba832d6660f633b10c75421f81c07da2b2f70744f095b36dd",
    "checkout/shipping.py": "cb3998ad5a89e3c608c2381cd70c41a8f1922b695fef9fad243e74f0988c8d71",
    "checkout/tax.py": "1f9569064a10a361aba114c1d8dc74e3ed738d36b3a640656c3173395b28a54f",
    "tests/test_quote.py": "b9c053132f6ae115d87bc7bac7bb0b77867d3afef01ac8d710fa6ff572706ea1",
}


def judge(answer: str) -> bool:
    """Right answer: 109.40 (euros). A currency sign or code, or a decimal comma, is fine."""
    from decimal import Decimal, InvalidOperation

    text = answer.strip().strip("`").upper().replace("EUR", "").replace("€", "").strip()
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text) == Decimal("109.40")
    except InvalidOperation:
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
