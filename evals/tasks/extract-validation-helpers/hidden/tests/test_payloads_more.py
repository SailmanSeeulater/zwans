import pytest

from shopapi.errors import ValidationError
from shopapi.orders import create_order
from shopapi.products import create_product
from shopapi.users import create_user

USER = {"name": "Ada", "email": "ada@example.org", "age": 36}
PRODUCT = {"sku": "ab-1", "title": "Mug", "price_cents": 899}
ORDER = {"customer_email": "A@B.co", "sku": " x-9 ", "quantity": 2}


def error(create, payload: dict) -> str:
    with pytest.raises(ValidationError) as caught:
        create(payload)
    assert str(caught.value) == f"{caught.value.field}: {caught.value.message}"
    return str(caught.value)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"name": None}, "name: must be text"),
        ({"name": "   "}, "name: must not be blank"),
        ({"email": 5}, "email: must be text"),
        ({"email": " "}, "email: must not be blank"),
        ({"email": "@example.org"}, "email: must be an email address"),
        ({"age": True}, "age: must be a whole number"),
        ({"age": 3.0}, "age: must be a whole number"),
        ({"age": -1}, "age: must be positive"),
    ],
)
def test_user_errors(change: dict, expected: str) -> None:
    assert error(create_user, {**USER, **change}) == expected


@pytest.mark.parametrize("field", ["name", "email", "age"])
def test_user_missing_fields(field: str) -> None:
    payload = {key: value for key, value in USER.items() if key != field}
    assert error(create_user, payload) == f"{field}: is required"


def test_user_fields_are_checked_in_order() -> None:
    assert error(create_user, {"email": "nope", "age": 0}) == "name: is required"
    assert error(create_user, {"name": "A", "email": "nope", "age": 0}) == (
        "email: must be an email address"
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"sku": ""}, "sku: must not be blank"),
        ({"title": 7}, "title: must be text"),
        ({"price_cents": "899"}, "price_cents: must be a whole number"),
        ({"price_cents": 0}, "price_cents: must be positive"),
        ({"sku": None, "title": None}, "sku: must be text"),
        ({"title": " ", "price_cents": 0}, "title: must not be blank"),
    ],
)
def test_product_errors(change: dict, expected: str) -> None:
    assert error(create_product, {**PRODUCT, **change}) == expected


def test_product_trims_text() -> None:
    product = create_product({"sku": " ab-1 ", "title": "  Big Mug ", "price_cents": 1})
    assert product == {"sku": "AB-1", "title": "Big Mug", "price_cents": 1}


def test_create_order() -> None:
    assert create_order(ORDER) == {"customer_email": "a@b.co", "sku": "X-9", "quantity": 2}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"customer_email": "a@b"}, "customer_email: must be an email address"),
        ({"customer_email": []}, "customer_email: must be text"),
        ({"sku": "\t"}, "sku: must not be blank"),
        ({"quantity": False}, "quantity: must be a whole number"),
        ({"quantity": -3}, "quantity: must be positive"),
        ({"customer_email": "bad", "quantity": 0}, "customer_email: must be an email address"),
    ],
)
def test_order_errors(change: dict, expected: str) -> None:
    assert error(create_order, {**ORDER, **change}) == expected


def test_order_missing_quantity() -> None:
    assert error(create_order, {"customer_email": "a@b.co", "sku": "x"}) == "quantity: is required"
