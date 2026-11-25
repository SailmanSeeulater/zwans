"""Imports, exports and reports after a merge."""

import csv
import io

from conftest import world
from orbit.io.csv_export import export_contacts
from orbit.io.csv_import import import_contacts
from orbit.io.json_export import contact_dossier, export_all
from orbit.io.vcard import export_vcards
from orbit.reports import activity_report, contact_summary, stage_moves_by_contact, top_contacts


def setup(crm) -> dict[str, str]:
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    return ids


def test_an_import_row_with_bs_id_updates_a(crm) -> None:
    ids = setup(crm)
    result = import_contacts(crm, f"id,title,tags\n{ids['b']},Countess of Lovelace,poet\n")
    assert result.summary() == "0 created, 1 updated, 0 skipped"
    assert result.updated == [ids["a"]]
    contact = crm.contact(ids["a"])
    assert contact.title == "Countess of Lovelace"
    assert "poet" in contact.tags


def test_an_import_row_with_bs_address_updates_a(crm) -> None:
    ids = setup(crm)
    result = import_contacts(crm, "email,phone\ncountess@home.example,+1 555 0100\n")
    assert result.created == []
    assert result.updated == [ids["a"]]
    assert crm.contact(ids["a"]).phones[-1] == "+1 555 0100"
    assert len(crm.list_contacts()) == 4


def test_the_csv_export_leaves_b_out(crm) -> None:
    ids = setup(crm)
    rows = list(csv.DictReader(io.StringIO(export_contacts(crm, include_archived=True))))
    assert [r["id"] for r in rows] == [ids["a"], ids["charles"], ids["grace"], ids["twin"]]
    assert rows[0]["email"] == "ada@analytical.example; countess@home.example"
    assert rows[0]["field:interests"] == "engines; poetry; looms; cards"


def test_the_contact_export_takes_bs_id(crm) -> None:
    ids = setup(crm)
    dossier = contact_dossier(crm, ids["b"])
    assert dossier["contact"]["id"] == ids["a"]
    assert "Collects punched cards" in [n["body"] for n in dossier["notes"]]
    assert [d["id"] for d in dossier["deals"]] == [ids["d1"], ids["d2"]]
    assert dossier == contact_dossier(crm, ids["a"])


def test_other_exports_leave_b_out(crm) -> None:
    ids = setup(crm)
    assert ids["b"] not in [c["id"] for c in export_all(crm)["contacts"]]
    assert "Augusta" not in export_vcards(crm)


def test_the_contact_summary_counts_a_once(crm) -> None:
    setup(crm)
    summary = contact_summary(crm)
    assert summary.total == 4
    assert summary.by_owner == {"kim": 2, "sam": 2}
    assert summary.by_tag == {"looms": 1, "vip": 1}
    assert summary.by_company == {"Analytical Engines": 1}


def test_the_activity_report_has_no_row_for_b(crm) -> None:
    ids = setup(crm)
    rows = {row.contact_id: row for row in activity_report(crm)}
    assert ids["b"] not in rows
    a = rows[ids["a"]]
    assert (a.notes, a.emails, a.open_tasks, a.deals) == (2, 2, 2, 2)
    assert a.open_value == 1_500_000
    assert a.name == "Ada Lovelace"


def test_top_contacts_count_each_deal_once(crm) -> None:
    ids = setup(crm)
    assert top_contacts(crm)[:2] == [
        (ids["a"], "Ada Lovelace", 1_500_000),
        (ids["charles"], "Charles Babbage", 1_500_000),
    ]
    assert ids["b"] not in [cid for cid, _, _ in top_contacts(crm)]


def test_stage_moves_are_credited_to_a(crm) -> None:
    ids = setup(crm)
    assert stage_moves_by_contact(crm) == {ids["a"]: 1, ids["charles"]: 1}
