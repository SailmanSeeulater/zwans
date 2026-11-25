import csv
import io

import pytest
from conftest import seed
from orbit.errors import ImportFailed, NotFound
from orbit.io.csv_export import export_contacts
from orbit.io.csv_import import import_contacts
from orbit.io.json_export import contact_dossier, export_all
from orbit.io.vcard import export_vcards


def rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_import_creates_and_updates(crm) -> None:
    ids = seed(crm)
    text = (
        "id,first_name,last_name,email,phone,company,tags\n"
        ",Alan,Turing,alan@bletchley.example,,Bletchley Park,codes;vip\n"
        f"{ids['grace']},,,grace.hopper@navy.example,,,\n"
        ",,,ADA@analytical.example,+44 1632 960000,,looms\n"
    )
    result = import_contacts(crm, text)
    assert result.summary() == "1 created, 2 updated, 0 skipped"
    alan = crm.contact(result.created[0])
    assert alan.tags == ["codes", "vip"]
    assert crm.company(alan.company_id).name == "Bletchley Park"
    grace = crm.contact(ids["grace"])
    assert grace.emails == ["grace@navy.example", "grace.hopper@navy.example"]
    assert grace.first_name == "Grace"
    ada = crm.contact(ids["ada"])
    assert ada.phones == ["+44 20 7946 0000", "+44 1632 960000"]
    assert ada.tags == ["looms", "vip"]


def test_rows_that_fail_are_skipped(crm) -> None:
    seed(crm)
    text = "id,first_name,email\nc99,Nobody,\n,Bad,not-an-address\n,Fine,fine@example.com\n"
    result = import_contacts(crm, text)
    assert [line for line, _ in result.skipped] == [2, 3]
    assert len(result.created) == 1


def test_a_dry_run_changes_nothing(crm) -> None:
    seed(crm)
    before = crm.store.document()
    result = import_contacts(crm, "first_name,email\nAlan,alan@bletchley.example\n", dry_run=True)
    assert len(result.created) == 1
    assert crm.store.document()["tables"] == before["tables"]
    assert crm.search("alan") == []


def test_unknown_columns_and_fields_stop_the_import(crm) -> None:
    with pytest.raises(ImportFailed):
        import_contacts(crm, "first_name,shoe_size\nAda,5\n")
    with pytest.raises(NotFound):
        import_contacts(crm, "first_name,field:colour\nAda,red\n")


def test_an_import_is_one_undo_step(crm) -> None:
    seed(crm)
    import_contacts(crm, "first_name\nOne\nTwo\nThree\n")
    assert len(crm.list_contacts()) == 6
    assert crm.undo() == "import contacts"
    assert len(crm.list_contacts()) == 3


def test_export_round_trips_through_import(crm) -> None:
    ids = seed(crm)
    crm.define_field("interests", "multi", choices=["looms", "engines"])
    crm.set_field(ids["ada"], "interests", ["engines", "looms"])
    exported = rows(export_contacts(crm))
    assert [r["id"] for r in exported] == [ids["ada"], ids["grace"], ids["charles"]]
    assert exported[0]["company"] == "Analytical Engines"
    assert exported[0]["field:interests"] == "engines; looms"
    result = import_contacts(crm, export_contacts(crm))
    assert result.summary() == "0 created, 3 updated, 0 skipped"


def test_the_contact_dossier(crm) -> None:
    ids = seed(crm)
    dossier = contact_dossier(crm, ids["ada"])
    assert dossier["contact"]["name"] == "Ada Lovelace"
    assert [n["body"] for n in dossier["notes"]] == ["Wants a quote for the difference engine"]
    assert [d["id"] for d in dossier["deals"]] == [ids["engine"]]
    assert [e["kind"] for e in dossier["timeline"]][:2] == ["created", "note"]


def test_whole_exports(crm) -> None:
    ids = seed(crm)
    everything = export_all(crm)
    assert [c["id"] for c in everything["contacts"]] == [ids["ada"], ids["grace"], ids["charles"]]
    cards = export_vcards(crm, [ids["ada"]])
    assert "FN:Ada Lovelace" in cards
    assert "ORG:Analytical Engines" in cards
    assert export_vcards(crm).count("BEGIN:VCARD") == 3
