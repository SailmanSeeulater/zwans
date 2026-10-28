import dataclasses

import pytest

from shipping.models import Address, Parcel
from shipping.rates import cheapest_first, rate_cents

HOME = Address("Oudegracht 1", "Utrecht", "3511AA")


def test_fields_in_order() -> None:
    assert [f.name for f in dataclasses.fields(Address)] == ["street", "city", "postcode", "country"]
    assert [f.name for f in dataclasses.fields(Parcel)] == [
        "weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
        "destination",
        "fragile",
        "tags",
    ]


def test_address_defaults_hash_and_repr() -> None:
    same = Address(street="Oudegracht 1", city="Utrecht", postcode="3511AA", country="NL")
    assert same == HOME
    assert hash(same) == hash(HOME)
    assert {HOME: 1}[same] == 1
    assert HOME.domestic
    assert not dataclasses.replace(HOME, country="BE").domestic
    assert repr(Address("a", "b", "c", "DE")) == (
        "Address(street='a', city='b', postcode='c', country='DE')"
    )


def test_address_cannot_change() -> None:
    with pytest.raises(AttributeError, match="cannot assign to field 'city'"):
        HOME.city = "Amsterdam"
    with pytest.raises(AttributeError):
        del HOME.street
    assert HOME.city == "Utrecht"


def test_equality_only_with_the_same_class() -> None:
    assert HOME != ("Oudegracht 1", "Utrecht", "3511AA", "NL")
    assert Parcel(1.0, 1, 1, 1, HOME) != "parcel"


def test_parcel_is_not_hashable() -> None:
    with pytest.raises(TypeError):
        hash(Parcel(1.0, 1, 1, 1, HOME))


def test_parcel_defaults_and_fresh_tags() -> None:
    first = Parcel(1.0, 1, 1, 1, HOME)
    second = Parcel(1.0, 1, 1, 1, HOME)
    first.tags.append("express")
    assert second.tags == []
    assert first != second
    assert second.fragile is False


def test_parcel_keywords_and_mutation() -> None:
    parcel = Parcel(
        weight_kg=3.5, length_cm=40, width_cm=30, height_cm=20, destination=HOME, fragile=True
    )
    assert parcel.volume_cm3 == 24000
    assert parcel.billable_weight() == 4.8
    parcel.weight_kg = 6
    assert parcel.billable_weight() == 6
    assert "fragile=True, tags=[]" in repr(parcel)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((0, 1, 1, 1), "weight must be positive"),
        ((-2.0, 1, 1, 1), "weight must be positive"),
        ((1.0, 0, 1, 1), "every side must be positive"),
        ((1.0, 1, 1, -1), "every side must be positive"),
    ],
)
def test_parcel_validation(args: tuple, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Parcel(*args, HOME)


def test_rates_still_work() -> None:
    heavy = Parcel(9.0, 10, 10, 10, HOME, tags=["express"])
    light = Parcel(0.5, 10, 10, 10, HOME)
    assert rate_cents(heavy) == 2960
    assert cheapest_first([heavy, light]) == [light, heavy]
