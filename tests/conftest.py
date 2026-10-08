from pathlib import Path

import pytest

from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    """A tool context whose workspace is this test's temporary folder."""
    return ToolContext(executor=LocalExecutor(tmp_path))
