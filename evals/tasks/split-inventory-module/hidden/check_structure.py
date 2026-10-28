"""Checks inventory/__init__.py was split into the four named modules."""

import ast
import sys
from pathlib import Path

package = Path(__file__).resolve().parent / "inventory"
PLACES = {
    "models": ["InsufficientStock", "Item", "StockMovement", "UnknownSku"],
    "storage": ["Warehouse", "dump_items", "load_items"],
    "pricing": ["bulk_discount", "markup_price", "quote_price"],
    "reports": ["low_stock", "movement_summary", "render_report", "stock_value"],
}
DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
problems = []


def defined_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, DEFINITIONS)}


found: dict[str, list[str]] = {}
for path in sorted(package.glob("*.py")):
    for name in defined_in(path):
        found.setdefault(name, []).append(path.stem)

for module, names in PLACES.items():
    if not (package / f"{module}.py").is_file():
        problems.append(f"inventory/{module}.py does not exist")
        continue
    for name in names:
        where = found.get(name, [])
        if where != [module]:
            problems.append(f"{name} should be defined only in inventory/{module}.py, not {where}")

init_definitions = defined_in(package / "__init__.py")
if init_definitions:
    problems.append(f"inventory/__init__.py still defines {sorted(init_definitions)}")

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
