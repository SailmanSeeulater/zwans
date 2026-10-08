from pathlib import Path

import pytest

from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    """A tool context whose workspace is this test's temporary folder."""
    spill_dir = tmp_path.parent / f"{tmp_path.name}-output"
    return ToolContext(executor=LocalExecutor(tmp_path, spill_dir=spill_dir))
