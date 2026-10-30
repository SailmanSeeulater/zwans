import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from helpers import collect, user
from pydantic import BaseModel

from zwans.events import HookReported, ToolResult, TurnEnded
from zwans.executor.local import LocalExecutor
from zwans.ext.hooks import Hooks, HookSpec
from zwans.loop import run_turn
from zwans.messages import Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.policy.rules import PolicyFile, load_policy
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.tools.base import Tool, ToolContext, ToolOutput
from zwans.tools.bash import BashTool

NO_PUSH = """\
import json, sys
call = json.load(sys.stdin)
if "git push" in call["args"].get("command", ""):
    print("Pushing is for the user to do. Commit, and say the branch is ready.", file=sys.stderr)
    sys.exit(1)
"""


class EchoInput(BaseModel):
    text: str


class EchoTool:
    name = "echo"
    description = "Return the given text unchanged."
    input_model = EchoInput
    read_only = True

    async def run(self, args: EchoInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content=args.text)


def python_hook(tmp_path: Path, name: str, source: str) -> str:
    script = tmp_path / f"{name}.py"
    script.write_text(source, encoding="utf-8")
    return f'"{sys.executable}" "{script}"'


def hooks(tmp_path: Path, *specs: HookSpec) -> Hooks:
    return Hooks(list(specs), tmp_path)


def call(name: str, **args: object) -> ModelResponse:
    return ModelResponse(
        content=[ToolUseBlock(id="call_1", name=name, input=dict(args))], stop_reason="tool_use"
    )


def done(text: str = "Done.") -> ModelResponse:
    return ModelResponse(content=[TextBlock(text=text)], stop_reason="end_turn")


def run(
    tmp_path: Path, script: list[ModelResponse], hook_set: Hooks
) -> tuple[list[object], list[Message], FakeProvider]:
    provider = FakeProvider(script)
    messages = [user("Go.")]
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    tools: list[Tool[Any]] = [BashTool(), EchoTool()]
    events = asyncio.run(collect(run_turn(provider, tools, messages, ctx, hooks=hook_set)))
    return list(events), messages, provider


def result_block(messages: list[Message]) -> ToolResultBlock:
    [block] = [b for m in messages for b in m.content if isinstance(b, ToolResultBlock)]
    return block


def test_a_pre_tool_hook_blocks_git_push_and_the_model_sees_why(tmp_path: Path) -> None:
    command = python_hook(tmp_path, "no_push", NO_PUSH)
    hook_set = hooks(tmp_path, HookSpec(event="pre_tool", tools="Bash", command=command))
    pushed = tmp_path / "pushed"
    script = [call("Bash", command=f"git push origin main && touch {pushed.name}"), done()]

    events, messages, _ = run(tmp_path, script, hook_set)

    assert not pushed.exists()
    block = result_block(messages)
    assert block.is_error
    assert block.content.startswith("A pre_tool hook blocked this call:")
    assert "Pushing is for the user to do" in block.content
    [reported] = [e for e in events if isinstance(e, HookReported)]
    assert (reported.event, reported.call_id) == ("pre_tool", "call_1")


def test_a_pre_tool_hook_that_passes_lets_the_call_run(tmp_path: Path) -> None:
    command = python_hook(tmp_path, "no_push", NO_PUSH)
    hook_set = hooks(tmp_path, HookSpec(event="pre_tool", command=command))

    events, messages, _ = run(tmp_path, [call("echo", text="hi"), done()], hook_set)

    assert result_block(messages) == ToolResultBlock(tool_use_id="call_1", content="hi")
    assert not [e for e in events if isinstance(e, HookReported)]


def test_hooks_only_run_for_the_tools_they_name(tmp_path: Path) -> None:
    command = python_hook(tmp_path, "refuse", "import sys; sys.exit(1)")
    hook_set = hooks(tmp_path, HookSpec(event="pre_tool", tools="Ba*", command=command))

    _, messages, _ = run(tmp_path, [call("echo", text="hi"), done()], hook_set)

    assert not result_block(messages).is_error


def test_a_hook_gets_the_call_as_json_and_runs_in_the_workspace(tmp_path: Path) -> None:
    source = (
        "import json, os, sys, pathlib\n"
        "data = json.load(sys.stdin)\n"
        "data['cwd'] = os.getcwd()\n"
        "pathlib.Path('seen.json').write_text(json.dumps(data))\n"
    )
    command = python_hook(tmp_path, "record", source)
    hook_set = hooks(tmp_path, HookSpec(event="pre_tool", command=command))

    run(tmp_path, [call("echo", text="hi"), done()], hook_set)

    seen = json.loads((tmp_path / "seen.json").read_text())
    assert seen["event"] == "pre_tool"
    assert seen["tool"] == "echo"
    assert seen["args"] == {"text": "hi"}
    assert Path(seen["cwd"]).resolve() == tmp_path.resolve()
    assert Path(seen["workspace"]) == tmp_path


def test_a_broken_or_slow_pre_tool_hook_blocks_rather_than_letting_calls_through(
    tmp_path: Path,
) -> None:
    slow = python_hook(tmp_path, "slow", "import time; time.sleep(30)")
    for spec in (
        HookSpec(event="pre_tool", command=slow, timeout=0.5),
        HookSpec(event="pre_tool", command="definitely-not-a-program-zwans"),
    ):
        _, messages, _ = run(tmp_path, [call("echo", text="hi"), done()], hooks(tmp_path, spec))
        block = result_block(messages)
        assert block.is_error
        assert block.content.startswith("A pre_tool hook blocked this call:")


def test_a_post_tool_hook_adds_its_message_to_the_result(tmp_path: Path) -> None:
    source = "import sys; print('lint: line 3 is too long'); sys.exit(1)"
    command = python_hook(tmp_path, "lint", source)
    hook_set = hooks(tmp_path, HookSpec(event="post_tool", command=command))

    events, messages, _ = run(tmp_path, [call("echo", text="hi"), done()], hook_set)

    block = result_block(messages)
    assert block.content == "hi\n\nA post_tool hook says: lint: line 3 is too long"
    assert not block.is_error
    [result] = [e for e in events if isinstance(e, ToolResult)]
    assert result.content == block.content


def test_a_stop_hook_keeps_the_turn_going_until_it_passes(tmp_path: Path) -> None:
    source = (
        "import pathlib, sys\n"
        "marker = pathlib.Path('stopped-once')\n"
        "if not marker.exists():\n"
        "    marker.touch()\n"
        "    print('The tests still fail.', file=sys.stderr)\n"
        "    sys.exit(1)\n"
    )
    command = python_hook(tmp_path, "tests_pass", source)
    hook_set = hooks(tmp_path, HookSpec(event="stop", command=command))

    events, messages, provider = run(tmp_path, [done("All done."), done("Fixed now.")], hook_set)

    assert len(provider.requests) == 2
    nudge = provider.requests[1][-1]
    assert nudge.role == "user"
    assert isinstance(nudge.content[0], TextBlock)
    assert "The tests still fail." in nudge.content[0].text
    assert isinstance(events[-1], TurnEnded) and events[-1].stop_reason == "end_turn"
    assert messages[-1].content == [TextBlock(text="Fixed now.")]


def test_a_workspace_policys_hooks_apply_only_once_trusted(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    (workspace / ".zwans").mkdir(parents=True)
    home.mkdir()
    (workspace / ".zwans" / "policy.toml").write_text(
        '[[hooks]]\nevent = "pre_tool"\ncommand = "echo hi"\n', encoding="utf-8"
    )
    (home / "policy.toml").write_text(
        '[[hooks]]\nevent = "stop"\ncommand = "true"\n', encoding="utf-8"
    )

    loaded = load_policy(workspace, home)

    assert loaded.untrusted == workspace / ".zwans" / "policy.toml"
    assert [hook.event for hook in loaded.policy.hooks] == ["stop"]  # the user's only
    assert PolicyFile(hooks=[HookSpec(event="stop", command="x")]).needs_trust()
