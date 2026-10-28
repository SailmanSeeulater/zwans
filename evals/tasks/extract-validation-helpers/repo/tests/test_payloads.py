import pytest

from shopapi.errors import ValidationError
from shopapi.orders import create_order
from shopapi.products import create_product
from shopapi.users import create_user


def test_create_user() -> None:
    user = create_user({"name": " Ada ", "email": "Ada@Example.org", "age": 36})
    assert user == {"name": "Ada", "email": "ada@example.org", "age": 36}


def test_create_user_bad_email() -> None:
    with pytest.raises(ValidationError, match="email: must be an email address"):
        create_user({"name": "Ada", "email": "ada@localhost", "age": 36})


def test_create_product() -> None:
    product = create_product({"sku": "ab-1", "title": "Mug", "price_cents": 899})
    assert product == {"sku": "AB-1", "title": "Mug", "price_cents": 899}


def test_create_order_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError) as caught:
        create_order({"customer_email": "a@b.co", "sku": "x", "quantity": 0})
    assert caught.value.field == "quantity"
    assert caught.value.message == "must be positive"
