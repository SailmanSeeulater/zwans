import pytest
from conftest import seed
from orbit.errors import Conflict, InvalidValue, NotFound


def ids_of(contacts) -> list[str]:
    return [c.id for c in contacts]


def test_tagging_and_lookups(crm) -> None:
    ids = seed(crm)
    crm.tag(ids["grace"], "VIP", "navy")
    assert ids_of(crm.tagged("vip")) == [ids["ada"], ids["grace"]]
    assert crm.tag_counts() == {"navy": 1, "vip": 2}
    crm.untag(ids["ada"], "vip")
    assert ids_of(crm.tagged("vip")) == [ids["grace"]]
    assert crm.contact(ids["ada"]).tags == []


def test_renaming_a_tag(crm) -> None:
    ids = seed(crm)
    crm.tag(ids["grace"], "vip")
    assert crm.rename_tag("vip", "key-account") == 2
    assert crm.tag_counts() == {"key-account": 2}


def test_defining_fields(crm) -> None:
    crm.define_field("size", "choice", choices=["small", "large"])
    with pytest.raises(Conflict):
        crm.define_field("size")
    with pytest.raises(InvalidValue):
        crm.define_field("Bad Name")
    with pytest.raises(InvalidValue):
        crm.define_field("kind", "choice")
    assert [d.name for d in crm.field_definitions()] == ["size"]


def test_values_are_checked_and_converted(crm) -> None:
    ids = seed(crm)
    crm.define_field("seats", "number")
    crm.define_field("renewal", "date")
    crm.define_field("interests", "multi", choices=["engines", "looms", "cards"])
    crm.set_field(ids["ada"], "seats", "12")
    crm.set_field(ids["ada"], "renewal", "2026-09-01")
    crm.set_field(ids["ada"], "interests", "looms; engines; looms")
    assert crm.contact(ids["ada"]).fields == {
        "seats": 12,
        "renewal": "2026-09-01",
        "interests": ["looms", "engines"],
    }
    with pytest.raises(InvalidValue):
        crm.set_field(ids["ada"], "seats", "many")
    with pytest.raises(InvalidValue):
        crm.set_field(ids["ada"], "interests", ["boats"])
    with pytest.raises(NotFound):
        crm.set_field(ids["ada"], "colour", "red")
    with pytest.raises(NotFound):
        crm.set_field("c99", "seats", 1)


def test_empty_values_clear_a_field(crm) -> None:
    ids = seed(crm)
    crm.define_field("nickname")
    crm.set_field(ids["ada"], "nickname", "Enchantress")
    crm.set_field(ids["ada"], "nickname", "")
    assert crm.contact(ids["ada"]).fields == {}
