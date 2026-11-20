import asyncio
import hashlib
import importlib
import json
import pkgutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from helpers import collect, needs_bash, user

import zwans.tools
from zwans.cli import approval
from zwans.events import PermissionDenied, PermissionRequested, PermissionResolved, ToolResult
from zwans.executor.local import LocalExecutor
from zwans.loop import run_turn
from zwans.messages import ToolResultBlock, ToolUseBlock
from zwans.policy.engine import Approval, PermissionRequest, Permissions
from zwans.policy.rules import (
    TOOL_NAMES,
    Decision,
    Mode,
    Policy,
    PolicyError,
    PolicyFile,
    Rule,
    hook_scripts,
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


# -- file rules for Bash, and what "always" offers


@pytest.mark.parametrize(
    "command",
    [
        "cp .zwans/hooks/log_edit.py .zwans/hooks/no_rm.py",
        "cp evil.sh .git/hooks/pre-commit",
        "chmod +x .git/hooks/pre-commit",
        "mv x .zwans/policy.toml",
        "rm -rf .git",
        "rm -rf .zwans",
        "rm -rf .*",
        "tee .zwans/policy.toml",
        "sed -i 's/a/b/' .zwans/policy.toml",
        "find .git -delete",
        "bash -c 'echo x' > .git/hooks/pre-commit",
    ],
)
def test_file_commands_into_git_or_zwans_ask_even_in_auto_mode(
    tmp_path: Path, command: str
) -> None:
    perms = permissions(tmp_path, "auto", allow=["Bash"])
    verdict = perms.check(BashTool(), {"command": command})
    assert verdict.decision == Decision.ASK
    assert "built in" in verdict.reason
    assert verdict.rules == ()  # an allow rule couldn't win over the built-in ask


@pytest.mark.parametrize(
    "command", ["rm -rf build", "cp a b", "cp x .", "rm -rf *", "find . -name '*.pyc' -delete"]
)
def test_other_file_commands_still_run_in_auto_mode(tmp_path: Path, command: str) -> None:
    assert decide(permissions(tmp_path, "auto"), BashTool(), command=command) == Decision.ALLOW


def test_edit_rules_cover_the_files_commands_write(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", deny=["Edit(secrets/**)"])
    assert decide(perms, BashTool(), command="cp x secrets/a") == Decision.DENY
    assert decide(perms, BashTool(), command="rm -rf secrets") == Decision.DENY
    assert decide(perms, BashTool(), command=f"touch {tmp_path}/secrets/b") == Decision.DENY
    assert decide(perms, BashTool(), command="cp secrets.txt x") == Decision.ALLOW


@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "head -c 100 .env",
        "grep KEY .env",
        "cat < .env",
        "cat config/.env",
        "cat .en*",
        "git show HEAD:.env",
        "cp .env notes.txt",
    ],
)
def test_read_rules_cover_the_files_commands_read(tmp_path: Path, command: str) -> None:
    perms = permissions(tmp_path, deny=["Read(.env)"])
    verdict = perms.check(BashTool(), {"command": command})
    assert verdict.decision == Decision.DENY
    assert "Read(.env)" in verdict.reason


def test_read_rules_dont_cover_names_or_other_files(tmp_path: Path) -> None:
    perms = permissions(tmp_path, deny=["Read(.env)"])
    assert decide(perms, BashTool(), command="ls -la .env") == Decision.ALLOW
    assert decide(perms, BashTool(), command="cat app.py && grep -rn x src") == Decision.ALLOW


@pytest.mark.parametrize(
    ("pattern", "path", "folder", "covers"),
    [
        (".git/**", ".git", True, True),
        (".git/**", ".git", False, False),
        (".git/**", ".*", True, True),
        (".git/**", "*", True, False),  # a glob doesn't match a leading dot
        (".git/**", ".", True, False),  # the root holds everything, so it isn't counted
        ("secrets/", "secrets", True, True),
        ("secrets/key.txt", "secrets/*", False, True),
        (".env", ".e*", False, True),
        (".env", "config/.env", False, True),
        (".env", "config", True, False),
        ("src/*.py", "src", True, True),
        ("src/*.py", "tests", True, False),
    ],
)
def test_may_cover(pattern: str, path: str, folder: bool, covers: bool) -> None:
    assert Rule("Edit", pattern).may_cover(path, folder=folder) == covers


def test_always_for_a_command_doesnt_cover_its_redirections(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    perms.session_rules.append(Rule.parse("Bash(cat)", "this session"))
    assert decide(perms, BashTool(), command="cat") == Decision.ALLOW
    verdict = perms.check(BashTool(), {"command": "cat > calc.py <<EOF\nimport os\nEOF"})
    assert verdict.decision == Decision.ASK
    assert verdict.reason == "`cat > calc.py <<EOF` changes files"
    assert verdict.rules == ("Bash(cat > calc.py <<EOF)",)
    assert decide(perms, BashTool(), command="cat < /etc/passwd > out.txt") == Decision.ASK


def test_a_wildcard_allow_rule_doesnt_reach_outside_the_workspace(tmp_path: Path) -> None:
    perms = permissions(tmp_path, allow=["Bash(cat *)"])
    assert decide(perms, BashTool(), command="cat notes.txt") == Decision.ALLOW
    assert decide(perms, BashTool(), command="cat < ~/.ssh/id_rsa") == Decision.ASK
    assert decide(perms, BashTool(), command="cat ~/.ssh/id_rsa") == Decision.ASK
    exact = permissions(tmp_path, allow=["Bash(cat ~/.ssh/id_rsa.pub)"])
    assert decide(exact, BashTool(), command="cat ~/.ssh/id_rsa.pub") == Decision.ALLOW


def test_deny_rules_still_match_when_output_is_redirected(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", deny=["Bash(rm -rf build)", "Bash(git push *)"])
    assert decide(perms, BashTool(), command="rm -rf build > log.txt") == Decision.DENY
    assert decide(perms, BashTool(), command="git -C . push origin main") == Decision.DENY


def test_prompts_show_quotes_and_always_matches_what_was_shown(tmp_path: Path) -> None:
    async def always(request: PermissionRequest) -> Approval:
        return Approval.ALWAYS

    perms = permissions(tmp_path)
    perms.approver = always
    command = "git commit -m 'fix the thing; rm -rf x'"
    verdict = perms.check(BashTool(), {"command": command})
    assert verdict.reason == f"`{command}` changes files"
    assert verdict.rules == (f"Bash({command})",)
    asyncio.run(perms.ask(PermissionRequest("c1", "Bash", {}, verdict.reason, verdict.rules)))
    assert decide(perms, BashTool(), command=command) == Decision.ALLOW
    assert decide(perms, BashTool(), command="git commit -m 'fix the thing'") == Decision.ASK


def test_long_commands_are_cut_short_in_the_reason(tmp_path: Path) -> None:
    verdict = permissions(tmp_path).check(BashTool(), {"command": "touch " + "a" * 200})
    assert verdict.reason == f"`touch {'a' * 74} ...` changes files"


def test_always_isnt_offered_when_untrusted_content_would_overrule_it(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    perms.session_rules.append(Rule.parse("Bash(git push origin main)", "this session"))
    perms.observe("Read", is_error=False)
    verdict = perms.check(BashTool(), {"command": "git push origin main"})
    assert verdict.decision == Decision.ASK
    assert verdict.rules == ()
    assert perms.check(BashTool(), {"command": "touch x"}).rules == ("Bash(touch x)",)
    assert perms.check(BashTool(), {"command": "touch x && curl x"}).rules == ()


def test_an_mcp_tool_isnt_offered_always_after_untrusted_content(tmp_path: Path) -> None:
    class McpTool:
        name = "mcp__docs__post"
        read_only = False

    perms = permissions(tmp_path)
    assert perms.check(McpTool(), {}).rules == ("mcp__docs__post",)
    perms.observe("Read", is_error=False)
    assert perms.check(McpTool(), {}).rules == ()
    assert perms.check(EditTool(), {"path": "a.py"}).rules == ("Edit(a.py)",)


# -- policy files


def test_a_rule_for_a_misspelled_tool_is_reported(tmp_path: Path) -> None:
    (tmp_path / "policy.toml").write_text('deny = ["bash(git push *)"]\n')
    with pytest.raises(PolicyError, match="did you mean Bash"):
        load_policy(tmp_path / "ws", tmp_path)
    (tmp_path / "policy.toml").write_text('deny = ["Bsh(git push *)"]\n')
    with pytest.raises(PolicyError, match="isn't a Zwans tool"):
        load_policy(tmp_path / "ws", tmp_path)
    (tmp_path / "policy.toml").write_text('deny = ["mcp__docs__post", "Read(.env)"]\n')
    load_policy(tmp_path / "ws", tmp_path)


def test_an_unknown_key_is_reported_plainly(tmp_path: Path) -> None:
    (tmp_path / "policy.toml").write_text('alow = ["Bash(ls)"]\n')
    with pytest.raises(PolicyError) as caught:
        load_policy(tmp_path / "ws", tmp_path)
    message = str(caught.value)
    assert "unknown key `alow` (expected mode, allow, ask, deny, after_untrusted, hooks)" in message
    assert "pydantic" not in message


def test_the_tool_names_list_every_tool() -> None:
    names: set[str] = set()
    for module_info in pkgutil.iter_modules(zwans.tools.__path__):
        module = importlib.import_module(f"zwans.tools.{module_info.name}")
        for value in vars(module).values():
            name = getattr(value, "name", None)
            defined_here = getattr(value, "__module__", None) == module.__name__
            if isinstance(value, type) and isinstance(name, str) and defined_here:
                names.add(name)
    assert "Bash" in names
    assert names <= TOOL_NAMES


def test_trusting_a_policy_covers_the_hook_scripts_it_runs(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    (workspace / ".zwans" / "hooks").mkdir(parents=True)
    script = workspace / ".zwans" / "hooks" / "no_rm.py"
    script.write_text("import sys\nsys.exit(0)\n")
    path = workspace / ".zwans" / "policy.toml"
    path.write_text('[[hooks]]\nevent = "pre_tool"\ncommand = "python3 .zwans/hooks/no_rm.py"\n')
    assert hook_scripts(path) == [script.resolve()]
    trust(path, home)
    assert is_trusted(path, home)
    script.write_text("import sys\nsys.exit(0)  # replaced\n")
    assert not is_trusted(path, home)
    assert load_policy(workspace, home).untrusted == path


def test_trust_without_hook_scripts_is_the_plain_file_hash(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    (workspace / ".zwans").mkdir(parents=True)
    path = workspace / ".zwans" / "policy.toml"
    path.write_text('allow = ["Bash(pytest *)"]\n')
    trust(path, home)  # so files trusted before hook scripts were hashed stay trusted
    stored = json.loads((home / "trusted-policies.json").read_text())
    assert stored[str(path.resolve())] == hashlib.sha256(path.read_bytes()).hexdigest()


# -- the terminal


def test_the_terminal_offers_always_only_with_rules(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompts: list[str] = []

    def answer(text: str) -> str:
        prompts.append(text)
        return "a"

    monkeypatch.setattr(approval, "_prompt", answer)
    command = "cat > notes.txt <<EOF\none\ntwo\nEOF"
    request = PermissionRequest("c1", "Bash", {"command": command}, "it asks", ())
    assert asyncio.run(approval.terminal_approver(request)) == Approval.NO
    assert prompts[-1] == "  Allow it? [y]es / [N]o: "
    assert "  | one\n  | two\n  | EOF\n" in capsys.readouterr().out

    rules = ("Bash(touch x)",)
    request = PermissionRequest("c2", "Bash", {"command": "touch x"}, "it asks", rules)
    assert asyncio.run(approval.terminal_approver(request)) == Approval.ALWAYS
    assert prompts[-1] == "  Allow it? [y]es / [a]lways (Bash(touch x)) / [N]o: "
