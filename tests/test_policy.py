import asyncio
import hashlib
import importlib
import json
import pkgutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from helpers import collect, needs_bash, needs_rg, user

import zwans.policy.rules
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
from zwans.tools.grep import GrepInput, GrepTool
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

    return Permissions(policy, inside, executor.relative, root=executor.root)


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
        "cd .git/hooks && cp evil.sh pre-commit",
        "cp --target-directory .git/hooks evil.sh",
        "cp -r t/.git .",
        "cp -r t/. .",
        "ln -s .git g",
        "cp evil.sh .git{,}",
        "find .git/hooks -name pre-commit -exec cp evil.sh {} \\;",
        "awk -i inplace 1 .zwans/policy.toml",
        "git checkout HEAD~1 -- .zwans/policy.toml",
        # A glob in any part of the path, which the shell expands to .git or .zwans.
        "cp evil .gi?/hooks/pre-commit",
        "echo x > .gi?/hooks/pre-commit",
        "rm .zwa*/policy.toml",
        "sed -i s/a/b/ .zwa*/policy.toml",
        "mv x .zwa*/policy.toml",
        "chmod +x .gi[t]/hooks/pre-commit",
        # -t in a group of options, or with its value attached.
        "cp -rt .git/hooks evil.sh",
        "cp -t.git/hooks evil.sh",
        # find looks at any depth, .git and .zwans included.
        "find . -name policy.toml -delete",
        "find . -name '*.toml' -delete",
        "find . -name '*.pyc' -delete",
        "find . -type f -exec rm {} +",
        "find . -name pre-commit -exec cp evil {} \\;",
        "find . -name hooks -execdir cp evil pre-commit \\;",
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
    "command",
    [
        "rm -rf build",
        "cp a b",
        "cp x .",
        "rm -rf *",
        "rm *.pyc",
        "find src -name '*.pyc' -delete",
        "cd src && rm -rf build",
        "pushd src && make && popd",
        "find src -name '*.tmp' -exec rm {} +",
        "cp -r src/ backup/",
        "git checkout main",
        "mkdir -p {src,tests}/pkg",
    ],
)
def test_other_file_commands_still_run_in_auto_mode(tmp_path: Path, command: str) -> None:
    assert decide(permissions(tmp_path, "auto"), BashTool(), command=command) == Decision.ALLOW


def test_edit_rules_cover_the_files_commands_write(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", deny=["Edit(secrets/**)"])
    assert decide(perms, BashTool(), command="cp x secrets/a") == Decision.DENY
    assert decide(perms, BashTool(), command="rm -rf secrets") == Decision.DENY
    touch = f"touch {tmp_path.as_posix()}/secrets/b"  # bash eats a backslash
    assert decide(perms, BashTool(), command=touch) == Decision.DENY
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
        "source .env",
        "cat .{env,x}",
        "find . -name .env -exec cat {} +",
    ],
)
def test_read_rules_cover_the_files_commands_read(tmp_path: Path, command: str) -> None:
    perms = permissions(tmp_path, deny=["Read(.env)"])
    verdict = perms.check(BashTool(), {"command": command})
    assert verdict.decision == Decision.DENY
    assert "Read(.env)" in verdict.reason


def test_a_deny_rule_wins_over_a_file_rule_that_asks(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", deny=["Bash(rm -rf *)", "Read(.env)"])
    assert decide(perms, BashTool(), command="rm -rf .git") == Decision.DENY
    assert decide(perms, BashTool(), command="cp .env .git/hooks/x") == Decision.DENY


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
        # Globs in folder parts, and on both sides.
        ("secrets/**", "secre*/key.pem", False, True),
        ("secrets/**", "secr?ts/key.pem", False, True),
        ("secrets/**", "sec*/k*", False, True),
        ("secrets/**", "src/*", False, False),
        ("secrets/**", "secre*", False, False),  # the folder alone isn't read
        ("*.pem", "key.p?m", False, True),
        ("*.pem", "id.pe*", False, True),
        ("*.pem", "*.py", False, False),
        ("*.pem", "*", False, True),
        (".env", ".[[:alpha:]]nv", False, True),  # a named class ends with its own ]
        (".env", ".[[:digit:]x]nv", False, True),
        (".env", "*", False, False),  # a glob doesn't match a leading dot
        (".git/**", ".gi[t]/hooks/pre-commit", True, True),
        (".git/**", ".gi[!t]/hooks", True, False),
        ("src/*.py", "s*/a.p?", False, True),
        ("a/b/**", "a/*/c", True, True),
        # A ** part stands for any folders, as for `find . -name x`.
        (".zwans/**", "**/policy.toml", True, True),
        (".zwans/**", "src/**/policy.toml", True, False),
        (".env", "x/**", False, True),
    ],
)
def test_may_cover(pattern: str, path: str, folder: bool, covers: bool) -> None:
    assert Rule("Edit", pattern).may_cover(path, folder=folder) == covers


@pytest.mark.parametrize("ignore_case", [True, False])
def test_path_rules_ignore_case_where_the_file_system_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ignore_case: bool
) -> None:
    # macOS and Windows: .GIT/config is .git/config.
    monkeypatch.setattr(zwans.policy.rules, "IGNORE_CASE", ignore_case)
    expected = Decision.ASK if ignore_case else Decision.ALLOW
    perms = permissions(tmp_path, "auto")
    assert decide(perms, BashTool(), command="cp evil.sh .GIT/hooks/pre-commit") == expected
    assert decide(perms, WriteTool(), path=".Zwans/policy.toml") == expected
    assert Rule("Read", ".env").may_cover(".EN*", folder=False) == ignore_case


def test_always_for_a_command_doesnt_cover_its_redirections(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    perms.session_rules.append(Rule.parse("Bash(cat)", "this session"))
    assert decide(perms, BashTool(), command="cat") == Decision.ALLOW
    verdict = perms.check(BashTool(), {"command": "cat > calc.py <<EOF\nimport os\nEOF"})
    assert verdict.decision == Decision.ASK
    assert verdict.reason == "`cat > calc.py <<EOF ...` changes files"
    assert verdict.rules == ("Bash(cat > calc.py <<EOF\nimport os\nEOF)",)
    assert decide(perms, BashTool(), command="cat < /etc/passwd > out.txt") == Decision.ASK


def test_always_for_a_here_document_covers_only_that_text(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    script = "bash <<'EOF'\necho hi\nEOF"
    verdict = perms.check(BashTool(), {"command": script})
    assert verdict.rules == (f"Bash({script})",)
    perms.session_rules.extend(Rule.parse(rule, "this session") for rule in verdict.rules)
    assert decide(perms, BashTool(), command=script) == Decision.ALLOW
    other = "bash <<'EOF'\nrm -rf ~\nEOF"
    assert decide(perms, BashTool(), command=other) == Decision.ASK


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
    shown = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert shown[-3:] == ["one", "two", "EOF"]  # the here-document's body is shown

    rules = ("Bash(touch x)",)
    request = PermissionRequest("c2", "Bash", {"command": "touch x"}, "it asks", rules)
    assert asyncio.run(approval.terminal_approver(request)) == Approval.ALWAYS
    assert prompts[-1] == "  Allow it? [y]es / [a]lways (Bash(touch x)) / [N]o: "


# -- audit findings: globs, folders, "always", Grep and read-only mode


@pytest.mark.parametrize(
    "command",
    [
        "cat secre*/key.pem",
        "cat secr?ts/key.pem",
        "head sec*/k*",
        "sed -n p secre*/k",
        "cat key.p?m",
        "cat id.pe*",
    ],
)
@pytest.mark.parametrize("mode", ["ask", "read-only"])
def test_read_rules_cover_globs_in_any_part_of_a_path(
    tmp_path: Path, command: str, mode: Mode
) -> None:
    perms = permissions(tmp_path, mode, deny=["Read(secrets/**)", "Read(*.pem)"])
    assert decide(perms, BashTool(), command=command) == Decision.DENY
    assert decide(perms, BashTool(), command="cat src/*.py") == Decision.ALLOW


async def _always(request: PermissionRequest) -> Approval:
    return Approval.ALWAYS


def _answer_always(perms: Permissions, command: str) -> tuple[str, ...]:
    perms.approver = _always
    verdict = perms.check(BashTool(), {"command": command})
    assert verdict.decision == Decision.ASK
    asyncio.run(perms.ask(PermissionRequest("c1", "Bash", {}, verdict.reason, verdict.rules)))
    return verdict.rules


def test_always_isnt_offered_for_a_command_substitution(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    assert _answer_always(perms, "cat $(git ls-files | head -1)") == ()
    assert decide(perms, BashTool(), command="cat $(echo ~/.ssh/id_rsa)") == Decision.ASK
    # Nor does a rule written for the placeholder allow one.
    perms.session_rules.append(Rule.parse("Bash(cat $(...))", "this session"))
    assert decide(perms, BashTool(), command="cat $(printf /etc/passwd)") == Decision.ASK
    assert decide(perms, BashTool(), command="rm -rf $(echo ~)") == Decision.ASK


def test_always_isnt_offered_for_a_script_piped_to_a_shell(tmp_path: Path) -> None:
    perms = permissions(tmp_path)
    assert _answer_always(perms, "git log --oneline | head -5 | bash") == ()
    assert _answer_always(perms, "cat notes.txt | python3") == ()
    for command in ["echo x | bash", "bash <<< 'rm -rf ~'", "echo 'import os' | python3"]:
        assert decide(perms, BashTool(), command=command) == Decision.ASK


def test_a_bare_shell_rule_doesnt_allow_a_here_document(tmp_path: Path) -> None:
    perms = permissions(tmp_path, allow=["Bash(bash)", "Bash(bash *)", "Bash(python3 *)"])
    assert decide(perms, BashTool(), command="bash <<'EOF'\nrm -rf ~\nEOF") == Decision.ASK
    assert decide(perms, BashTool(), command="cat notes.txt | bash") == Decision.ASK
    assert decide(perms, BashTool(), command="python3 - <<'EOF'\nprint(1)\nEOF") == Decision.ASK
    assert decide(perms, BashTool(), command="python3 x.py") == Decision.ALLOW


@pytest.mark.parametrize(
    "command",
    [
        "env -C . rm -rf build",
        "env -C src git push origin main",
        "env --chdir=. git push origin main",
        "env -S 'rm -rf build'",
        "env PATH=. git push origin main",
    ],
)
def test_deny_rules_see_the_command_env_runs_in_another_folder(
    tmp_path: Path, command: str
) -> None:
    perms = permissions(tmp_path, deny=["Bash(rm -rf *)", "Bash(git push *)"])
    assert decide(perms, BashTool(), command=command) == Decision.DENY
    other = command.replace("rm -rf build", "ls").replace("git push origin main", "ls")
    verdict = permissions(tmp_path).check(BashTool(), {"command": other})
    assert verdict.decision == Decision.ASK
    assert verdict.rules == ()  # no rule can say which folder's files it uses


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (BashTool(), {"command": "cp a .git/hooks/pre-commit"}),
        (BashTool(), {"command": "chmod +x .git/hooks/pre-commit"}),
        (BashTool(), {"command": "mv x .zwans/policy.toml"}),
        (BashTool(), {"command": "tee .zwans/policy.toml"}),
        (BashTool(), {"command": "rm -rf migrations"}),
        (EditTool(), {"path": ".git/config"}),
        (EditTool(), {"path": "migrations/0001.py"}),
        (ReadTool(), {"path": "secrets/key.txt"}),
    ],
)
def test_read_only_mode_refuses_what_an_ask_rule_covers(
    tmp_path: Path, tool: Any, args: dict[str, Any]
) -> None:
    policy = Policy.default()
    file = PolicyFile(mode="read-only", ask=["Edit(migrations/**)", "Read(secrets/**)"])
    policy.add(file, "test")
    perms = Permissions(policy, lambda path: True, LocalExecutor(tmp_path).relative)
    verdict = perms.check(tool, args)
    assert verdict.decision == Decision.DENY
    assert "read-only mode" in verdict.reason


def test_read_rules_cover_the_grep_tool(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "read-only", deny=["Read(.env)", "Read(secrets/**)"])
    assert decide(perms, GrepTool(), pattern=".", path=".env") == Decision.DENY
    assert decide(perms, GrepTool(), pattern=".", path="config/.env") == Decision.DENY
    assert decide(perms, GrepTool(), pattern=".", path="secrets") == Decision.DENY
    assert decide(perms, GrepTool(), pattern=".", path="src") == Decision.ALLOW
    assert decide(perms, GrepTool(), pattern=".") == Decision.ALLOW


def test_a_folder_search_hides_what_read_rules_cover() -> None:
    policy = Policy.default()
    policy.add(PolicyFile(deny=["Read(.env)", "Read(secrets/)"], ask=["Read(a[1].txt)"]), "t")
    assert policy.hidden_from_search(".") == [".env", "secrets/**", "a\\[1\\].txt"]
    assert policy.hidden_from_search("secrets") == [".env", "a\\[1\\].txt"]  # asked already


@needs_rg
def test_grep_through_a_folder_skips_files_read_rules_cover(tmp_path: Path) -> None:
    for name in (".env", "src/.env", "secrets/key.txt", "src/secrets/key.txt", "src/app.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("KEY=fake\n", encoding="utf-8")
    policy = Policy.default()
    policy.add(PolicyFile(deny=["Read(.env)", "Read(secrets/**)"]), "test")
    tool = GrepTool(hidden=policy.hidden_from_search)
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    # glob="*" would let a later glob put .env back; the rules' globs come last.
    found = asyncio.run(tool.run(GrepInput(pattern="KEY", glob="*", files_only=True), ctx))
    assert sorted(found.content.splitlines()) == ["src/app.py", "src/secrets/key.txt"]
    found = asyncio.run(tool.run(GrepInput(pattern="KEY", path="src", files_only=True), ctx))
    assert sorted(found.content.splitlines()) == ["src/app.py", "src/secrets/key.txt"]


def test_policy_errors_show_escape_codes_as_text(tmp_path: Path) -> None:
    (tmp_path / "policy.toml").write_text('"\\u001b]0;PWNED\\u0007" = 1\n', encoding="utf-8")
    with pytest.raises(PolicyError) as caught:
        load_policy(tmp_path / "ws", tmp_path)
    assert "\x1b" not in str(caught.value)
    assert "\x07" not in str(caught.value)
    assert "\\x1b]0;PWNED\\x07" in str(caught.value)
    (tmp_path / "policy.toml").write_text('deny = ["Nope(\\u001b[8mhidden)"]\n', encoding="utf-8")
    with pytest.raises(PolicyError) as caught:
        load_policy(tmp_path / "ws", tmp_path)
    assert "\x1b" not in str(caught.value)
    assert "\\x1b[8mhidden" in str(caught.value)


def test_a_link_out_of_the_workspace_counts_as_outside(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "src").mkdir()
    (workspace / "src" / "a.py").write_text("x")
    (tmp_path / "credentials").write_text("secret")
    (workspace / "notes").symlink_to(tmp_path / "credentials")
    (workspace / "docs" / "setup.md").symlink_to(tmp_path / "credentials")
    (workspace / "home").symlink_to(tmp_path)
    read_only = permissions(workspace, "read-only")
    for command in ["cat notes", "grep KEY notes", "cd home && cat credentials", "cat docs/*"]:
        assert decide(read_only, BashTool(), command=command) == Decision.DENY, command
    assert decide(read_only, BashTool(), command="cat src/*") == Decision.ALLOW
    assert decide(read_only, BashTool(), command="ls -la notes") == Decision.ALLOW  # names only
    auto = permissions(workspace, "auto")
    for command in ["tee notes", "cp x notes", "sed -i s/a/b/ notes"]:
        verdict = auto.check(BashTool(), {"command": command})
        assert (verdict.decision, verdict.rules) == (Decision.ASK, ()), command
        assert "symbolic link" in verdict.reason


@pytest.mark.parametrize(
    "command",
    [
        "grep -r KEY secrets",
        "rg KEY secrets",
        "cd secrets && grep -rn KEY .",
        "cp -r secrets /tmp/s",
        "mv secrets public",
        "tar czf /tmp/s.tgz secrets",
        "diff -r secrets /tmp/old",
    ],
)
def test_reading_a_folder_counts_as_reading_what_read_rules_cover_in_it(
    tmp_path: Path, command: str
) -> None:
    perms = permissions(tmp_path, "auto", deny=["Read(secrets/**)", "Read(.env)"])
    assert decide(perms, BashTool(), command=command) == Decision.DENY


@pytest.mark.parametrize(
    "command", ["grep -rn foo src", "rg foo", "cp -r src backup", "grep -r x .", "ls secrets"]
)
def test_other_folders_can_still_be_searched_and_copied(tmp_path: Path, command: str) -> None:
    perms = permissions(tmp_path, "auto", deny=["Read(secrets/**)", "Read(.env)"])
    assert decide(perms, BashTool(), command=command) == Decision.ALLOW


@pytest.mark.parametrize(
    "command",
    [
        "bash <(git log -1 --format=%s)",
        "source <(git log -1)",
        "bash /dev/stdin <<< ls",
        "python3 /dev/stdin <<< 'print(1)'",
        "$(which python3) -m pytest",
        "bash $(git ls-files | head -1)",
    ],
)
def test_always_isnt_offered_when_the_script_isnt_shown(tmp_path: Path, command: str) -> None:
    perms = permissions(tmp_path)
    assert _answer_always(perms, command) == ()


@pytest.mark.parametrize(
    "command",
    [
        "/usr/bin/git push origin main",
        "/usr/bin/env -C . git push origin main",
        "/bin/bash -c 'git push origin main'",
        "HOME=/tmp git push origin main",
        "git -c core.sshCommand=x push origin main",
        "eval 'git push origin main'",
    ],
)
def test_deny_rules_see_through_paths_variables_and_eval(tmp_path: Path, command: str) -> None:
    perms = permissions(tmp_path, deny=["Bash(git push *)"])
    assert decide(perms, BashTool(), command=command) == Decision.DENY


@pytest.mark.parametrize(
    "command",
    [
        "x='a[$(touch pwned)]'; echo $((x))",
        "x='$(touch pwned)'; echo ${x@P}",
        "PS4='$(touch pwned)' bash -xc ls",
        'X=-vPATH; printf "$X" .; ls',
        "PYTHONPATH=. pip list",
        "python3 -m pip list",
        "sed 's/x/touch pwned/e' a.txt",
        "gawk '@load \"./evil\"; BEGIN {}'",
        "git grep --open-files-in-pager=sh -l x",
        "sort --compress=sh a.txt",
        "find . -name '*env' -exec cat {} +",
        "xargs -a .env echo",
    ],
)
def test_read_only_mode_refuses_what_runs_code_or_reads_denied_files(
    tmp_path: Path, command: str
) -> None:
    perms = permissions(tmp_path, "read-only", deny=["Read(.env)"])
    assert decide(perms, BashTool(), command=command) == Decision.DENY
