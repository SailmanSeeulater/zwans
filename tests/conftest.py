import os
import sys
from pathlib import Path

import pytest

from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    """A tool context whose workspace is this test's temporary folder."""
    spill_dir = tmp_path.parent / f"{tmp_path.name}-output"
    return ToolContext(executor=LocalExecutor(tmp_path, spill_dir=spill_dir))


@pytest.fixture
def python_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the Python running the tests first on PATH, so `python -m pytest` in a shell
    command finds the same Python, with pytest installed."""
    monkeypatch.setenv("PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")
