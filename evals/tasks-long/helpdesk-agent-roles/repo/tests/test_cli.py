import json


def setup_desk(cli) -> None:
    assert cli("agent", "add", "maria", "Maria Lopez", "maria@ourdesk.example")[0] == 0
    assert cli("customer", "add", "Jane Doe", "--email", "jane@example.org", "--phone", "+1 555 0101")[0] == 0
    assert cli("ticket", "new", "C-1", "Printer", "It jams")[0] == 0


def test_a_ticket_from_start_to_finish(cli) -> None:
    setup_desk(cli)
    code, out, _ = cli("--as", "maria", "ticket", "take", "T-1")
    assert code == 0 and "T-1 is yours" in out
    assert cli("--as", "maria", "ticket", "reply", "T-1", "Have you tried turning it off?")[0] == 0
    code, out, _ = cli("ticket", "show", "T-1")
    assert "assignee:  maria" in out
    assert "email:     jane@example.org" in out
    assert "Have you tried turning it off?" in out
    assert cli("ticket", "status", "T-1", "solved")[0] == 0
    code, out, _ = cli("outbox")
    assert "survey_request" in out


def test_errors_exit_1(cli) -> None:
    setup_desk(cli)
    code, _, err = cli("ticket", "show", "T-9")
    assert code == 1
    assert err.startswith("error: no ticket")
    assert cli("--as", "ghost", "ticket", "show", "T-1")[0] == 1
    assert cli("ticket", "frobnicate")[0] == 2


def test_customers_on_the_command_line(cli) -> None:
    setup_desk(cli)
    code, out, _ = cli("customer", "show", "C-1")
    assert "phone:        +1 555 0101" in out
    assert "tickets:      T-1" in out
    code, out, _ = cli("customer", "list")
    assert "jane@example.org" in out
    assert cli("customer", "edit", "C-1", "--address", "1 Main St")[0] == 0
    assert "1 Main St" in cli("customer", "show", "C-1")[1]


def test_search_reports_and_export(cli, tmp_path) -> None:
    setup_desk(cli)
    code, out, _ = cli("search", "printer")
    assert "T-1" in out and "jane@example.org" in out
    code, out, _ = cli("report", "sla", "--json")
    assert json.loads(out)["by_priority"]["normal"]["tickets"] == 1
    target = tmp_path / "out.csv"
    assert cli("export", "tickets", "--out", str(target))[0] == 0
    assert "jane@example.org" in target.read_text()
    code, out, _ = cli("audit", "--target", "T-1")
    assert "ticket.created" in out


def test_macros_and_bulk(cli) -> None:
    setup_desk(cli)
    assert cli("ticket", "new", "C-1", "Scanner", "Also broken")[0] == 0
    assert cli("macro", "add", "Hold", "--action", "set_status=pending", "--action", "add_tag=waiting")[0] == 0
    assert cli("macro", "run", "M-1", "T-1")[0] == 0
    assert cli("bulk", "T-1", "T-2", "--priority", "high")[0] == 0
    code, out, _ = cli("ticket", "list")
    assert out.count("high") == 2
    assert "pending" in out


def test_mail_in(cli, tmp_path) -> None:
    raw = tmp_path / "mail.eml"
    raw.write_text("From: Sam <sam@new.example>\nSubject: Hi\n\nHello there\n")
    code, out, _ = cli("mail-in", str(raw))
    assert code == 0 and "new ticket: T-1" in out
