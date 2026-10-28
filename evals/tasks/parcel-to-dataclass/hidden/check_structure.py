"""Checks Address and Parcel are dataclasses with no hand-written dunder methods left."""

import ast
import sys
from pathlib import Path

source = (Path(__file__).resolve().parent / "shipping" / "models.py").read_text(encoding="utf-8")
classes = {
    node.name: node for node in ast.parse(source).body if isinstance(node, ast.ClassDef)
}
GENERATED = {"__init__", "__repr__", "__eq__", "__hash__", "__setattr__", "__delattr__"}
problems = []


def dataclass_decorator(node: ast.ClassDef) -> ast.expr | None:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "dataclass":
            return decorator
    return None


for name in ("Address", "Parcel"):
    node = classes.get(name)
    if node is None:
        problems.append(f"shipping/models.py no longer defines {name}")
        continue
    if dataclass_decorator(node) is None:
        problems.append(f"{name} is not decorated with @dataclass")
    for statement in node.body:
        if isinstance(statement, ast.FunctionDef) and statement.name in GENERATED:
            problems.append(f"{name} still hand-writes {statement.name}")
        targets = statement.targets if isinstance(statement, ast.Assign) else []
        for target in targets:
            if isinstance(target, ast.Name) and target.id in GENERATED:
                problems.append(f"{name} still sets {target.id} by hand")

address = classes.get("Address")
decorator = dataclass_decorator(address) if address else None
frozen = isinstance(decorator, ast.Call) and any(
    keyword.arg == "frozen"
    and isinstance(keyword.value, ast.Constant)
    and keyword.value.value is True
    for keyword in decorator.keywords
)
if address and not frozen:
    problems.append("Address should be a frozen dataclass")

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
