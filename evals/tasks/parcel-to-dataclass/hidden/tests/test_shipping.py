import pytest

from shipping.labels import label
from shipping.models import Address, Parcel
from shipping.rates import by_destination, rate_cents

HOME = Address("Oudegracht 1", "Utrecht", "3511AA")
PARIS = Address("Rue de Rivoli 2", "Paris", "75001", country="FR")


def test_repr() -> None:
    parcel = Parcel(2.0, 30, 20, 10, HOME)
    assert repr(parcel) == (
        "Parcel(weight_kg=2.0, length_cm=30, width_cm=20, height_cm=10, "
        "destination=Address(street='Oudegracht 1', city='Utrecht', postcode='3511AA', "
        "country='NL'), fragile=False, tags=[])"
    )


def test_equality() -> None:
    assert Parcel(1.5, 10, 10, 10, HOME) == Parcel(1.5, 10, 10, 10, HOME)
    assert Parcel(1.5, 10, 10, 10, HOME) != Parcel(1.5, 10, 10, 10, PARIS)


def test_address_is_immutable() -> None:
    with pytest.raises(AttributeError):
        HOME.city = "Amsterdam"


def test_rates() -> None:
    assert rate_cents(Parcel(2.0, 30, 20, 10, HOME)) == 640
    assert rate_cents(Parcel(1.0, 50, 40, 30, PARIS, fragile=True)) == 4730


def test_label_and_grouping() -> None:
    parcel = Parcel(1.0, 10, 10, 10, PARIS, tags=["express"])
    assert label(parcel) == "Rue de Rivoli 2\n75001 Paris\nFR\nEXPRESS"
    assert list(by_destination([parcel])) == [PARIS]
