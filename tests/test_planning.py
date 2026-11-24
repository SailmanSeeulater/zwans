import asyncio
from pathlib import Path

import pytest
from test_cli_input import opened_session
from test_policy import decide, permissions
from test_server import Server, connect, handshake, say, until, write

from zwans import planning
from zwans.cli.commands import Commands, Send
from zwans.events import Event, PermissionDenied, PlanModeChanged, ToolResult, TurnStarted
from zwans.messages import Message, TextBlock
from zwans.policy.rules import Decision
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.tools.base import ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.read import ReadTool
from zwans.tools.write import WriteTool


def texts(message: Message) -> list[str]:
    return [b.text for b in message.content if isinstance(b, TextBlock)]


def test_planning_judges_calls_as_read_only_and_ignores_allow_rules(tmp_path: Path) -> None:
    perms = permissions(tmp_path, "auto", allow=["Edit", "Bash(rm *)"])
    assert decide(perms, EditTool(), path="a.py") == Decision.ALLOW
    assert decide(perms, BashTool(), command="rm a.py") == Decision.ALLOW

    perms.planning = True

    assert perms.mode == "read-only" and perms.policy.mode == "auto"  # the policy is untouched
    assert decide(perms, ReadTool(), path="a.py") == Decision.ALLOW
    assert decide(perms, BashTool(), command="ls -la") == Decision.ALLOW
    assert decide(perms, BashTool(), command="rm a.py") == Decision.DENY
    refused = perms.check(EditTool(), {"path": "a.py"})
    assert refused.decision == Decision.DENY
    assert "plan mode, so nothing changes until the user approves the plan" in refused.reason
    perms.planning = False
    assert decide(perms, EditTool(), path="a.py") == Decision.ALLOW


def test_a_planned_turn_carries_a_note_the_user_never_sees(
    ctx: ToolContext, tmp_path: Path
) -> None:
    edit_call = write("a.txt", "x")
    provider = FakeProvider([edit_call, say("1. Write a.txt"), say("Done."), say("Ok.")])
    seen: list[Event] = []
    session = Session(
        provider,
        [WriteTool()],
        ctx,
        "S",
        listeners=[seen.append],
        permissions=permissions(tmp_path, "auto"),
    )

    async def go() -> None:
        assert session.set_planning(True) and not session.set_planning(True)
        await session.send("Add a.txt")
        assert session.set_planning(False, approved=True)
        await session.send(planning.GO)
        await session.send("Thanks")

    asyncio.run(go())

    planned, approved, after = (
        provider.requests[0][-1],
        provider.requests[2][-1],
        provider.requests[3][-1],
    )
    assert texts(planned) == ["Add a.txt", planning.PLANNING]
    assert texts(approved) == [planning.GO, planning.GO_NOTE]
    assert texts(after) == ["Thanks"]  # the note is said once
    assert [e.prompt for e in seen if isinstance(e, TurnStarted)] == [
        "Add a.txt",
        planning.GO,
        "Thanks",
    ]
    assert session.prompt_of(1) == "Add a.txt"
    denied = [e for e in seen if isinstance(e, PermissionDenied)]
    assert len(denied) == 1 and "plan mode" in denied[0].reason
    assert not (tmp_path / "a.txt").exists()
    changes = [(e.on, e.approved) for e in seen if isinstance(e, PlanModeChanged)]
    assert changes == [(True, False), (False, True)]
    assert any(isinstance(e, ToolResult) and e.is_error for e in seen)


def test_leaving_plan_mode_without_approving_says_so_once(ctx: ToolContext, tmp_path: Path) -> None:
    provider = FakeProvider([say("Plan."), say("Ok."), say("Ok.")])
    session = Session(provider, [], ctx, "S", listeners=[], permissions=permissions(tmp_path))

    async def go() -> None:
        session.set_planning(True)
        await session.send("Plan it")
        session.set_planning(False)
        await session.send("Never mind, just tell me")
        await session.send("And then")

    asyncio.run(go())
    assert texts(provider.requests[1][-1]) == ["Never mind, just tell me", planning.ENDED]
    assert texts(provider.requests[2][-1]) == ["And then"]


def test_plan_mode_needs_checked_calls(ctx: ToolContext) -> None:
    session = Session(FakeProvider([]), [], ctx, "S", listeners=[])
    with pytest.raises(ValueError, match="Plan mode needs"):
        session.set_planning(True)


def test_plan_and_go_commands_in_the_terminal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    opened = opened_session(tmp_path, workspace, ["A plan.", "Did it."])
    commands = Commands(opened)

    async def go() -> None:
        assert await commands.run("/go") is None  # no plan yet
        assert await commands.run("/plan off") is None
        assert await commands.run("/plan Add a cache\nfor the API") == Send(
            "Add a cache\nfor the API"
        )
        assert opened.session.planning and opened.session.permissions
        assert opened.session.permissions.planning
        assert await commands.run("/plan") is None
        assert await commands.run("/go") == Send(planning.GO)
        assert not opened.session.planning
        assert await commands.run("/plan") is None
        assert await commands.run("/plan off") is None
        assert not opened.session.planning

    asyncio.run(go())
    out = capsys.readouterr().out
    assert out.count("There's no plan to carry out") == 1
    assert "Plan mode isn't on." in out
    assert out.count("Plan mode: the model can look but not change anything") == 2
    assert "Plan mode is already on." in out
    assert "Plan mode is off" in out
    asyncio.run(opened.close())


def test_plan_mode_over_the_websocket(tmp_path: Path) -> None:
    server = Server(tmp_path)
    provider = FakeProvider(
        [write("a.txt", "1"), say("1. Write a.txt"), write("a.txt", "1"), say("Wrote it.")]
    )
    with server.client:
        session_id = server.new_session(provider)
        with connect(server, session_id) as ws:
            status, _ = handshake(ws)
            assert status["planning"] is False
            ws.send_json({"type": "go"})
            refused = until(ws, "server_error")[-1]
            ws.send_json({"type": "plan", "on": True, "task": "Add a.txt"})
            planned = until(ws, "turn_ended")
            ws.send_json({"type": "go"})
            done = until(ws, "turn_ended")
            final = until(ws, "status")[-1]

    assert "plan mode isn't on" in refused["message"]
    assert [m["on"] for m in planned if m["type"] == "plan_mode"] == [True]
    assert any(m["type"] == "permission_denied" for m in planned)
    assert next(m for m in planned if m["type"] == "status")["planning"] is True
    assert [(m["on"], m["approved"]) for m in done if m["type"] == "plan_mode"] == [(False, True)]
    assert (server.workspace / "a.txt").read_text() == "1"
    assert final["planning"] is False
