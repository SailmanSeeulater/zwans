"""The web UI's "Wtf is Zwans" page lists every built-in tool, and nothing that isn't one."""

import importlib
import pkgutil
import re
from pathlib import Path

import zwans.tools

PAGE = Path(__file__).parent.parent / "web" / "src" / "app" / "about" / "page.tsx"


def builtin_tools() -> set[str]:
    names: set[str] = set()
    for module in pkgutil.iter_modules(zwans.tools.__path__):
        loaded = importlib.import_module(f"zwans.tools.{module.name}")
        for value in vars(loaded).values():
            name = getattr(value, "name", None)
            own = isinstance(value, type) and value.__module__ == loaded.__name__
            if own and isinstance(name, str):
                names.add(name)
    return names


def test_the_about_page_lists_every_builtin_tool() -> None:
    listed = re.findall(r'^\s*\["(\w+)", "', PAGE.read_text(), re.MULTILINE)

    assert len(listed) == len(set(listed))
    assert set(listed) == builtin_tools()
    assert f"The {len(listed)} built-in tools" in PAGE.read_text()
