import json


def test_adding_and_showing_a_contact(cli) -> None:
    code, out, _ = cli(
        "contact",
        "add",
        "Ada",
        "Lovelace",
        "--email",
        "ada@analytical.example",
        "--company",
        "Analytical Engines",
        "--tag",
        "vip",
    )
    assert code == 0
    assert out.strip() == "Added c1 Ada Lovelace"
    code, out, _ = cli("contact", "show", "c1")
    assert "Ada Lovelace  [c1]" in out
    assert "Analytical Engines" in out
    code, out, _ = cli("--json", "contact", "show", "c1")
    assert json.loads(out)["tags"] == ["vip"]


def test_errors_go_to_stderr(cli) -> None:
    code, out, err = cli("contact", "show", "c7")
    assert code == 1
    assert err.strip() == "error: No contact 'c7'."


def test_deals_notes_and_the_timeline(cli) -> None:
    cli("contact", "add", "Ada", "Lovelace")
    assert cli("deal", "add", "Engine", "--amount", "12,000.50", "--contact", "c1")[0] == 0
    assert cli("deal", "move", "d1", "qualified", "--contact", "c1")[0] == 0
    assert cli("note", "c1", "Wants a quote")[0] == 0
    code, out, _ = cli("timeline", "c1")
    lines = out.strip().splitlines()
    assert [line.split()[2] for line in lines] == ["Lovelace"] * 4
    assert "Engine: lead -> qualified" in lines[2]
    code, out, _ = cli("--json", "deal", "show", "d1")
    assert json.loads(out)["amount"] == 1_200_050


def test_search_tags_and_duplicates(cli) -> None:
    cli("contact", "add", "Ada", "Lovelace", "--email", "ada@a.example")
    cli("contact", "add", "Ada", "Lovelace", "--email", "ada@b.example")
    cli("tag", "c2", "vip")
    assert cli("search", "lovelace")[1].count("Ada Lovelace") == 2
    assert "c2" in cli("tagged", "vip")[1]
    assert cli("dupes")[1].strip() == "c1 Ada Lovelace  c2 Ada Lovelace"
    assert cli("dupes", "c1")[1].strip() == "c2  (name)"


def test_undo_from_the_command_line(cli) -> None:
    cli("contact", "add", "Ada")
    cli("note", "c1", "Hello")
    assert cli("undo")[1].strip() == "Undid add note"
    assert cli("timeline", "c1")[1].count("note") == 0
    assert cli("history")[1].strip().endswith("add contact  (2 rows)")


def test_import_export_and_reports(cli, tmp_path) -> None:
    source = tmp_path / "in.csv"
    source.write_text("first_name,last_name,email,owner\nAda,Lovelace,ada@a.example,sam\n")
    assert cli("import", str(source))[1].strip() == "1 created, 0 updated, 0 skipped"
    code, out, _ = cli("export", "csv")
    assert out.splitlines()[1].startswith("c1,Ada,Lovelace,ada@a.example")
    code, out, _ = cli("--json", "report", "contacts")
    assert json.loads(out)["by_owner"] == {"sam": 1}
    code, out, _ = cli("export", "contact", "c1")
    assert json.loads(out)["contact"]["id"] == "c1"


def test_webhooks_from_the_command_line(cli) -> None:
    cli("contact", "add", "Ada")
    assert (
        cli("webhook", "add", "https://hooks.example/x", "--contact", "c1", "--secret", "s")[0] == 0
    )
    cli("note", "c1", "Hello")
    code, out, _ = cli("outbox")
    assert out.split()[:4] == ["ob1", "wh1", "note.added", "pending"]


def test_backups_from_the_command_line(cli, tmp_path) -> None:
    cli("contact", "add", "Ada")
    code, out, _ = cli("backup", "--dir", str(tmp_path / "b"))
    saved = out.split()[-1]
    cli("contact", "add", "Grace")
    assert cli("restore", saved)[1].strip() == "Restored 1 contacts and 0 deals"
    assert cli("contact", "list")[1].strip() == "c1     Ada"
