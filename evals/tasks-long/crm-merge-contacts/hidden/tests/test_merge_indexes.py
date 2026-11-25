"""Search, duplicate detection and tags see a merge straight away (and after reopening)."""

import pytest
from conftest import clock, world
from orbit import Crm


def ids_of(contacts) -> list[str]:
    return [c.id for c in contacts]


@pytest.fixture(params=["live", "reopened"])
def merged(request, path):
    crm = Crm.open(path, clock=clock())
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    if request.param == "reopened":
        crm.save()
        crm = Crm.open(path, clock=clock())
    return crm, ids


def test_b_is_not_found_by_its_name(merged) -> None:
    crm, ids = merged
    assert crm.search("augusta") == []
    assert crm.search("king") == []
    assert crm.search("augusta", include_archived=True) == []


def test_a_is_found_by_what_b_brought(merged) -> None:
    crm, ids = merged
    assert ids_of(crm.search("punched")) == [ids["a"]]
    assert ids_of(crm.search("loom pattern")) == [ids["a"]]
    assert ids_of(crm.search("countess")) == [ids["a"]]
    assert ids_of(crm.search("1632")) == [ids["a"]]
    assert ids_of(crm.search("ada looms")) == [ids["a"]]
    assert ids_of(crm.search("lovelace")) == [ids["a"]]


def test_b_is_no_longer_a_duplicate(merged) -> None:
    crm, ids = merged
    assert crm.duplicates() == [(ids["grace"], ids["twin"])]
    assert crm.duplicates_of(ids["a"]) == []


def test_as_new_addresses_count_for_duplicates(merged) -> None:
    crm, ids = merged
    assert ids_of(crm.find_by_email("Countess@home.example")) == [ids["a"]]
    twin = crm.add_contact("Lady", "Byron", emails=["countess@home.example"])
    assert crm.duplicates_of(ids["a"]) == [twin.id]
    phone_twin = crm.add_contact("Someone", phones=["01632 960111"])
    assert phone_twin.id in crm.duplicates_of(ids["a"])


def test_tags_count_a_once(merged) -> None:
    crm, ids = merged
    assert ids_of(crm.tagged("looms")) == [ids["a"]]
    assert ids_of(crm.tagged("vip")) == [ids["a"]]
    assert crm.tag_counts() == {"looms": 1, "vip": 1}


def test_before_the_merge_both_were_there(crm) -> None:
    ids = world(crm)
    assert ids_of(crm.search("punched")) == [ids["b"]]
    assert crm.duplicates()[0] == (ids["a"], ids["b"])
    assert crm.tag_counts() == {"looms": 1, "vip": 2}
