"""Checks parse_amt was renamed to parse_amount everywhere, with no alias left behind."""

import ast
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
old = re.compile(r"\bparse_amt\b")
problems = []

for path in sorted(root.rglob("*")):
    relative = path.relative_to(root)
    if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
        continue
    if not path.is_file() or path.name == "check_structure.py":
        continue
    if path.suffix not in {".py", ".md"}:
        continue
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if old.search(line):
            problems.append(f"{relative}:{number} still says parse_amt")

money = ast.parse((root / "ledger" / "money.py").read_text(encoding="utf-8"))
defined = {node.name for node in money.body if isinstance(node, ast.FunctionDef)}
if "parse_amount" not in defined:
    problems.append("ledger/money.py does not define a function named parse_amount")

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
