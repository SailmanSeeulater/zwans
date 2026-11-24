"""How the policy judges the tools for data, images, archives, code, history, timing, the
machine and CI: by the paths they read or write, the commands they run, or the host they ask."""

from pathlib import Path
from typing import Any

from zwans.executor.local import LocalExecutor
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Policy, PolicyFile
from zwans.tools.archives import ArchiveTool
from zwans.tools.audit import AuditTool
from zwans.tools.benchmark import BenchmarkTool
from zwans.tools.bisect import BisectTool
from zwans.tools.ci import CITool
from zwans.tools.cron import CronTool
from zwans.tools.data import DataTool
from zwans.tools.env_vars import EnvTool
from zwans.tools.history import HistoryTool
from zwans.tools.image_diff import ImageDiffTool
from zwans.tools.imports import ImportsTool
from zwans.tools.openapi import OpenAPITool


def test_the_policy_knows_the_newest_tools(tmp_path: Path) -> None:
    policy = Policy.default()
    policy.add(
        PolicyFile(
            mode="ask", deny=["Read(private/**)", "Edit(locked/**)"], allow=["CI(github.com)"]
        ),
        "test",
    )
    executor = LocalExecutor(tmp_path)
    permissions = Permissions(policy, lambda path: True, executor.relative, root=executor.root)

    def decide(tool: Any, args: dict[str, Any]) -> Decision:
        return permissions.check(tool, args).decision

    # Read rules cover what they read, both images of a comparison included.
    assert decide(DataTool(), {"path": "private/users.csv"}) == Decision.DENY
    assert decide(DataTool(), {"path": "sales.csv"}) == Decision.ALLOW
    assert decide(ImageDiffTool(), {"before": "a.png", "path": "b.png"}) == Decision.ALLOW
    assert decide(ImageDiffTool(), {"before": "private/a.png", "path": "b.png"}) == Decision.DENY
    assert decide(HistoryTool(), {"path": "private/keys.py", "line": 3}) == Decision.DENY
    assert decide(ImportsTool(), {"path": "private"}) == Decision.DENY
    assert decide(EnvTool(), {"path": "."}) == Decision.ALLOW
    assert decide(CronTool(), {"expression": "0 9 * * 1-5"}) == Decision.ALLOW
    # OpenAPI: a file is judged like reading it, a URL like a request to its host.
    assert decide(OpenAPITool(), {"source": "private/api.json"}) == Decision.DENY
    assert decide(OpenAPITool(), {"source": "api.json"}) == Decision.ALLOW
    assert decide(OpenAPITool(), {"source": "http://localhost:8000/openapi.json"}) == Decision.ASK
    # Extracting is writing where it extracts to.
    assert decide(ArchiveTool(), {"path": "site.zip", "to": "locked/site"}) == Decision.DENY
    assert decide(ArchiveTool(), {"path": "site.zip", "to": "site"}) == Decision.ASK
    # Commands are judged as Bash would judge them; requests by their host.
    assert decide(BisectTool(), {"good": "v1", "test": "pytest -x"}) == Decision.ASK
    assert decide(BenchmarkTool(), {"command": "python slow.py"}) == Decision.ASK
    assert decide(AuditTool(), {"path": "."}) == Decision.ASK
    assert decide(CITool(), {}) == Decision.ALLOW
