"""The command line: --as with roles, exit status 3, and redacted output everywhere."""

import json

import pytest
from conftest import JANE_ADDRESS, JANE_EMAIL, JANE_PHONE, REDACTED, leaks


@pytest.fixture
def desk_cli(cli, tmp_path):
    for agent_id, role in (("vic", "viewer"), ("ana", "agent"), ("lou", "lead"), ("ada", "admin")):
        assert cli("agent", "add", agent_id, agent_id.title(), f"{agent_id}@ourdesk.example", "--role", role)[0] == 0
    assert cli("customer", "add", "Jane Doe", "--email", JANE_EMAIL, "--phone", JANE_PHONE,
               "--address", JANE_ADDRESS)[0] == 0
    mail = tmp_path / "in.eml"
    mail.write_text(f"From: Jane Doe <{JANE_EMAIL}>\nSubject: Printer\n\nIt jams.\n")
    assert cli("mail-in", str(mail))[0] == 0
    assert cli("ticket", "assign", "T-1", "ana")[0] == 0
    return cli


def test_roles_on_the_command_line(desk_cli) -> None:
    code, out, _ = desk_cli("agent", "list")
    assert code == 0
    line = [l for l in out.splitlines() if l.startswith("lou")][0]
    assert "lead" in line
    assert desk_cli("agent", "role", "vic", "agent")[0] == 0
    assert "agent" in [l for l in desk_cli("agent", "list")[1].splitlines() if l.startswith("vic")][0]
    # An unknown role: refused (1) or, with argparse choices, a usage error (2); both fit.
    assert desk_cli("agent", "add", "zed", "Zed", "zed@ourdesk.example", "--role", "boss")[0] in (1, 2)


def test_denied_commands_exit_3(desk_cli) -> None:
    code, out, err = desk_cli("--as", "vic", "ticket", "reply", "T-1", "Hello")
    assert code == 3
    assert err.startswith("denied: ")
    assert desk_cli("--as", "lou", "ticket", "delete", "T-1")[0] == 3
    assert desk_cli("--as", "ana", "agent", "role", "ana", "admin")[0] == 3
    assert desk_cli("--as", "vic", "export", "tickets")[0] == 3
    assert desk_cli("--as", "ana", "search", "email:example")[0] == 3
    code, out, _ = desk_cli("audit", "--action", "permission.denied")
    assert out.count("permission.denied") == 5
    assert desk_cli("--as", "ana", "ticket", "reply", "T-1", "On it")[0] == 0


@pytest.mark.parametrize(
    "argv",
    [
        ("ticket", "show", "T-1"),
        ("ticket", "list"),
        ("ticket", "history", "T-1"),
        ("customer", "show", "C-1"),
        ("customer", "list"),
        ("search", "printer"),
        ("export", "tickets"),
        ("export", "customers"),
        ("report", "sla"),
        ("report", "sla", "--json"),
        ("audit",),
        ("outbox", "--all"),
        ("template", "preview", "agent_assigned", "T-1"),
    ],
)
def test_what_an_agent_sees_is_redacted(desk_cli, monkeypatch, argv) -> None:
    monkeypatch.setenv("DESKLINE_NOW", "2026-03-05T09:00:00Z")
    assert desk_cli("jobs", "run")[0] == 0
    code, out, err = desk_cli("--as", "ana", *argv)
    assert code == 0, err
    assert leaks(out) == []
    assert REDACTED in out
    code, out, _ = desk_cli("--as", "lou", *argv)
    assert code == 0
    assert leaks(out) != []


def test_saved_searches_on_the_command_line(desk_cli) -> None:
    assert desk_cli("--as", "lou", "saved", "add", "All", "", "--shared")[0] == 0
    code, out, _ = desk_cli("--as", "vic", "saved", "run", "Q-1")
    assert code == 0
    assert "T-1" in out and leaks(out) == []
    assert desk_cli("--as", "ana", "saved", "add", "Shared", "status:new", "--shared")[0] == 3


def test_viewers_see_redacted_detail(desk_cli) -> None:
    code, out, _ = desk_cli("--as", "vic", "customer", "show", "C-1")
    assert f"email:        {REDACTED}" in out
    assert f"address:      {REDACTED}" in out
    code, out, _ = desk_cli("--as", "vic", "report", "sla", "--json")
    assert leaks(json.loads(out)) == []
