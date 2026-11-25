"""orbit merge, and merged ids on the command line."""

import json


def two_adas(cli) -> None:
    cli("contact", "add", "Ada", "Lovelace", "--email", "ada@analytical.example")
    cli("contact", "add", "Augusta", "King", "--email", "countess@home.example", "--tag", "looms")
    cli("note", "c2", "Collects punched cards")
    cli("deal", "add", "Loom", "--amount", "3000", "--contact", "c2")


def test_merging_from_the_command_line(cli) -> None:
    two_adas(cli)
    code, out, err = cli("merge", "c1", "c2")
    assert code == 0, err
    code, out, _ = cli("--json", "contact", "show", "c1")
    shown = json.loads(out)
    assert shown["emails"] == ["ada@analytical.example", "countess@home.example"]
    assert shown["tags"] == ["looms"]
    assert cli("contact", "list")[1].strip().splitlines() == [
        "c1     Ada Lovelace                 ada@analytical.example"
    ]


def test_the_merged_id_works_in_later_commands(cli) -> None:
    two_adas(cli)
    cli("merge", "c1", "c2")
    code, out, _ = cli("--json", "contact", "show", "c2")
    assert json.loads(out)["id"] == "c1"
    assert cli("note", "c2", "Still reachable")[0] == 0
    code, out, _ = cli("--json", "timeline", "c2")
    entries = json.loads(out)
    assert {e["contact_id"] for e in entries} == {"c1"}
    assert {e["contact_name"] for e in entries} == {"Ada Lovelace"}
    # Each CLI run restarts the ORBIT_NOW clock, so where the note sorts among the merge's
    # own entries depends on how many readings the merge took; only ask that it's there.
    assert "Still reachable" in {e["summary"] for e in entries}
    code, out, _ = cli("export", "contact", "c2")
    assert len(json.loads(out)["notes"]) == 2
    code, out, _ = cli("--json", "deal", "show", "d1")
    assert json.loads(out)["contact_ids"] == ["c1"]
    assert cli("search", "augusta")[1].strip() == "No matches."


def test_merge_errors_on_the_command_line(cli) -> None:
    two_adas(cli)
    code, _, err = cli("merge", "c1", "c1")
    assert code == 1
    assert err.startswith("error: ")
    assert cli("merge", "c1", "c9")[0] == 1


def test_undoing_a_merge_from_the_command_line(cli) -> None:
    two_adas(cli)
    cli("merge", "c1", "c2")
    code, out, _ = cli("undo")
    assert out.strip() == "Undid merge contacts"
    code, out, _ = cli("--json", "contact", "show", "c2")
    assert json.loads(out)["name"] == "Augusta King"
    assert cli("dupes")[1].strip() == "No likely duplicates."


def test_new_contacts_after_a_merge_get_new_ids(cli) -> None:
    two_adas(cli)
    cli("merge", "c1", "c2")
    out = cli("contact", "add", "Grace", "Hopper")[1].strip()
    assert out.startswith("Added c")
    assert out.split()[1] not in ("c1", "c2")
    assert json.loads(cli("--json", "contact", "show", "c2")[1])["id"] == "c1"
