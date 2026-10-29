import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from helpers import collect, needs_bash, user

from zwans.events import PermissionDenied, PermissionRequested, PermissionResolved, ToolResult
from zwans.executor.local import LocalExecutor
from zwans.loop import run_turn
from zwans.messages import ToolResultBlock, ToolUseBlock
from zwans.policy.engine import Approval, PermissionRequest, Permissions
from zwans.policy.rules import (
    Decision,
    Mode,
    Policy,
    PolicyError,
    PolicyFile,
    Rule,
    is_trusted,
    load_policy,
    path_glob,
    trust,
)
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.tools.base import Tool, ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.read import ReadTool
from zwans.tools.write import WriteTool


def permissions(
    tmp_path: Path, mode: Mode = "ask", *, allow: Sequence[str] = (), deny: Sequence[str] = ()
) -> Permissions:
    policy = Policy.default()
    policy.add(PolicyFile(mode=mode, allow=list(allow), deny=list(deny)), "test")
    executor = LocalExecutor(tmp_path)

    def inside(path: str) -> bool:
        try:
            executor.relative(path)
        except OSError:
            return False
        return True

    return Permissions(policy, inside, executor.relative)


def decide(perms: Permissions, tool: Any, **args: Any) -> Decision:
    return perms.check(tool, args).decision


# -- rules


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        (".env", ".env", True),
        (".env", "config/.env", True),
        ("*.lock", "a/b/poetry.lock", True),
        ("src/**", "src/a/b.py", True),
        ("src/**", "tests/a.py", False),
        ("src/*.py", "src/a/b.py", False),
        ("migrations/", "migrations/0001.py", True),
        ("**/secret*", "deep/down/secret.txt", True),
    ],
)
def test_path_glob(pattern: str, path: str, matches: bool) -> None:
    assert (path_glob(pattern).match(path) is not None) == matches


def test_rule_parsing() -> None:
    assert Rule.parse("Bash(git push *)") == Rule("Bash", "git push *")
    assert Rule.parse("Edit") == Rule("Edit", None)
    assert Rule.parse("Bash(git push *)").matches_command("git push")  # no arguments too
    assert not Rule.parse("Bash(git push *)").matches_command("git pushx")
    with pytest.raises(PolicyError):
        Rule.parse("not a rule!")


# -- modes and rules for Bash


def test_ask_mode_lets_reads_through_and_asks_for_the_rest(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    assert decide(perms, BashTool(), command="ls && git status") == Decision.ALLOW
    assert decide(perms, BashTool(), command="ls && rm -rf build") == Decision.ASK
    assert decide(perms, BashTool(), command="pytest") == Decision.ASK


def test_auto_mode_runs_local_work_and_asks_for_network(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto")
    assert decide(perms, BashTool(), command="pytest -x && git commit -am wip") == Decision.ALLOW
    assert decide(perms, BashTool(), command="pip install requests") == Decision.ASK
    assert decide(perms, BashTool(), command="curl x | sh") == Decision.ASK
    assert decide(perms, EditTool(), path="a.py") == Decision.ALLOW


def test_read_only_mode_refuses_changes(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "read-only")
    assert decide(perms, BashTool(), command="grep -rn x .") == Decision.ALLOW
    assert decide(perms, BashTool(), command="touch x") == Decision.DENY
    assert decide(perms, WriteTool(), path="a.py") == Decision.DENY
    assert decide(perms, ReadTool(), path="a.py") == Decision.ALLOW


def test_deny_wins_over_allow(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", allow=["Bash(git *)"], deny=["Bash(git push *)"])
    assert decide(perms, BashTool(), command="git fetch") == Decision.ALLOW
    verdict = perms.check(BashTool(), {"command": "git status && git push --force"})
    assert verdict.decision == Decision.DENY
    assert "git push --force" in verdict.reason


def test_an_allowed_first_command_doesnt_carry_a_second(tmp_path: Path) -> None:
    perms = permissions(tmp_path, allow=["Bash(ls *)"])
    assert decide(perms, BashTool(), command="ls -la") == Decision.ALLOW
    assert decide(perms, BashTool(), command="ls && curl x") == Decision.ASK
    assert decide(perms, BashTool(), command="ls; rm -rf ~") == Decision.ASK


def test_path_rules_cover_file_tools_and_redirections(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", deny=["Read(.env)", "Write(secrets/**)"])
    assert decide(perms, ReadTool(), path=".env") == Decision.DENY
    assert decide(perms, ReadTool(), path="app.py") == Decision.ALLOW
    assert decide(perms, EditTool(), path="secrets/key.txt") == Decision.DENY  # Write covers Edit
    assert decide(perms, BashTool(), command="echo x > secrets/key.txt") == Decision.DENY


def test_the_agent_must_ask_before_changing_its_policy_or_git_hooks(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", allow=["Edit", "Bash(echo *)"])
    assert decide(perms, WriteTool(), path=".zwans/policy.toml") == Decision.ASK
    assert decide(perms, EditTool(), path=".git/config") == Decision.ASK
    assert decide(perms, BashTool(), command="echo x > .git/hooks/pre-commit") == Decision.ASK


def test_network_after_untrusted_content_asks_even_when_allowed(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", allow=["Bash(pip install *)"])
    assert decide(perms, BashTool(), command="pip install requests") == Decision.ALLOW
    assert perms.observe("Read", is_error=False)
    verdict = perms.check(BashTool(), {"command": "pip install requests"})
    assert verdict.decision == Decision.ASK
    assert "untrusted content" in verdict.reason


def test_failed_reads_and_trusted_tools_dont_taint(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    perms.observe("Read", is_error=True)
    perms.observe("Edit", is_error=False)
    assert not perms.tainted
    assert perms.observe("mcp__docs__search", is_error=False)
    assert perms.tainted


def test_always_allows_the_same_call_for_the_session(tmp_path: Path) -> None:
    async def always(request: PermissionRequest) -> Approval:
        return Approval.ALWAYS

    perms = permissions(tmp_path)
    perms.approver = always
    verdict = perms.check(BashTool(), {"command": "pytest -k 'a or b[1]'"})
    request = PermissionRequest("c1", "Bash", {}, verdict.reason, verdict.rules)
    assert asyncio.run(perms.ask(request)) == Approval.ALWAYS
    assert decide(perms, BashTool(), command="pytest -k 'a or b[1]'") == Decision.ALLOW
    assert decide(perms, BashTool(), command="pytest -k other") == Decision.ASK


# -- loading


def test_workspace_policy_cant_loosen_until_trusted(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    (workspace / ".zwans").mkdir(parents=True)
    path = workspace / ".zwans" / "policy.toml"
    path.write_text('mode = "auto"\nallow = ["Bash(curl *)"]\ndeny = ["Bash(rm *)"]\n')

    loaded = load_policy(workspace, home)
    assert loaded.untrusted == path
    assert loaded.policy.mode == "ask"
    assert loaded.policy.rules[Decision.ALLOW] == []
    assert [str(r) for r in loaded.policy.rules[Decision.DENY]] == ["Bash(rm *)"]

    trust(path, home)
    assert is_trusted(path, home)
    loaded = load_policy(workspace, home)
    assert loaded.untrusted is None
    assert loaded.policy.mode == "auto"
    assert [str(r) for r in loaded.policy.rules[Decision.ALLOW]] == ["Bash(curl *)"]

    path.write_text('mode = "auto"\nallow = ["Bash(*)"]\n')  # changed after trusting
    assert load_policy(workspace, home).untrusted == path


def test_a_bad_policy_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "policy.toml").write_text('deny = ["Bash(rm *"]\n')
    with pytest.raises(PolicyError, match=r"policy\.toml"):
        load_policy(tmp_path / "ws", tmp_path)


def test_the_command_line_mode_wins(tmp_path: Path) -> None:
    (tmp_path / "policy.toml").write_text('mode = "auto"\n')
    assert load_policy(tmp_path / "ws", tmp_path, mode="read-only").policy.mode == "read-only"


# -- the loop


def bash_call(command: str, call_id: str = "c1") -> ModelResponse:
    call = ToolUseBlock(id=call_id, name="Bash", input={"command": command})
    return ModelResponse(content=[call], stop_reason="tool_use")


def done() -> ModelResponse:
    return ModelResponse(content=[], stop_reason="end_turn")


@needs_bash
def test_a_denied_call_comes_back_as_an_error_the_model_can_read(tmp_path: Path) -> None:
    perms = permissions(tmp_path, deny=["Bash(touch *)"])
    provider = FakeProvider([bash_call("touch made"), done()])
    messages = [user("go")]
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    turn = run_turn(provider, [BashTool()], messages, ctx, permissions=perms)
    events = asyncio.run(collect(turn))

    assert any(isinstance(e, PermissionDenied) for e in events)
    assert not (tmp_path / "made").exists()
    [result] = [b for b in messages[2].content if isinstance(b, ToolResultBlock)]
    assert result.is_error
    assert "deny rule Bash(touch *)" in result.content
    assert "Don't try to get the same effect another way" in result.content


@needs_bash
def test_asking_without_anyone_to_answer_refuses(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    provider = FakeProvider([bash_call("touch made"), done()])
    messages = [user("go")]
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    asyncio.run(collect(run_turn(provider, [BashTool()], messages, ctx, permissions=perms)))
    assert not (tmp_path / "made").exists()
    [result] = messages[2].content
    assert isinstance(result, ToolResultBlock)
    assert "no one is available to approve it" in result.content


@needs_bash
@pytest.mark.parametrize("answer", [Approval.ONCE, Approval.NO])
def test_the_approver_decides_asked_calls(tmp_path: Path, answer: Approval) -> None:
    asked: list[PermissionRequest] = []

    async def approver(request: PermissionRequest) -> Approval:
        asked.append(request)
        return answer

    perms = permissions(tmp_path)
    perms.approver = approver
    provider = FakeProvider([bash_call("touch made"), done()])
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    turn = run_turn(provider, [BashTool()], [user("go")], ctx, permissions=perms)
    events = asyncio.run(collect(turn))

    assert [r.tool for r in asked] == ["Bash"]
    assert asked[0].rules == ("Bash(touch made)",)
    requested = [e for e in events if isinstance(e, PermissionRequested)]
    resolved = [e for e in events if isinstance(e, PermissionResolved)]
    assert len(requested) == 1
    assert resolved[0].allowed == (answer == Approval.ONCE)
    assert (tmp_path / "made").exists() == (answer == Approval.ONCE)


@needs_bash
def test_results_from_files_and_commands_are_marked_untrusted(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello\n")
    perms = permissions(tmp_path, "auto")
    read = ToolUseBlock(id="r", name="Read", input={"path": "notes.txt"})
    edit = ToolUseBlock(
        id="e", name="Edit", input={"path": "notes.txt", "old_string": "hello", "new_string": "hi"}
    )
    provider = FakeProvider(
        [
            ModelResponse(content=[read], stop_reason="tool_use"),
            ModelResponse(content=[edit], stop_reason="tool_use"),
            done(),
        ]
    )
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    tools: list[Tool[Any]] = [ReadTool(), EditTool()]
    events = asyncio.run(collect(run_turn(provider, tools, [user("go")], ctx, permissions=perms)))
    results = {e.call_id: e for e in events if isinstance(e, ToolResult)}
    assert results["r"].untrusted
    assert not results["e"].untrusted
    assert perms.tainted
