"""Checks the duplicated payload checks now live in shopapi/validation.py only."""

import ast
import sys
from pathlib import Path

package = Path(__file__).resolve().parent / "shopapi"
problems = []

validation_file = package / "validation.py"
if not validation_file.is_file():
    print("shopapi/validation.py does not exist")
    sys.exit(1)
validation = ast.parse(validation_file.read_text(encoding="utf-8"))
defined = {node.name for node in validation.body if isinstance(node, ast.FunctionDef)}
for name in ("require_text", "require_positive_int", "require_email"):
    if name not in defined:
        problems.append(f"shopapi/validation.py does not define {name}")

for module in ("users", "orders", "products"):
    tree = ast.parse((package / f"{module}.py").read_text(encoding="utf-8"))
    uses_helpers = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise):
            problems.append(f"shopapi/{module}.py line {node.lineno} still raises an error itself")
        if isinstance(node, ast.Name) and node.id == "isinstance":
            problems.append(f"shopapi/{module}.py line {node.lineno} still checks types inline")
        if isinstance(node, ast.ImportFrom) and (
            node.module == "shopapi.validation" or (node.level == 1 and node.module == "validation")
            or (node.level == 1 and node.module is None and any(a.name == "validation" for a in node.names))
            or (node.module == "shopapi" and any(a.name == "validation" for a in node.names))
        ):
            uses_helpers = True
        if isinstance(node, ast.Import) and any(a.name == "shopapi.validation" for a in node.names):
            uses_helpers = True
    if not uses_helpers:
        problems.append(f"shopapi/{module}.py does not import from shopapi.validation")

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
