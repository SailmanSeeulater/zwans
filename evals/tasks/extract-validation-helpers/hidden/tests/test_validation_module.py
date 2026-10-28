import pytest

from shopapi.errors import ValidationError
from shopapi.validation import require_email, require_positive_int, require_text


def test_require_text() -> None:
    assert require_text({"a": "  hi "}, "a") == "hi"
    with pytest.raises(ValidationError, match="^a: is required$"):
        require_text({}, "a")
    with pytest.raises(ValidationError, match="^a: must be text$"):
        require_text({"a": 1}, "a")
    with pytest.raises(ValidationError, match="^a: must not be blank$"):
        require_text({"a": " "}, "a")


def test_require_positive_int() -> None:
    assert require_positive_int({"n": 4}, "n") == 4
    with pytest.raises(ValidationError, match="^n: is required$"):
        require_positive_int({}, "n")
    with pytest.raises(ValidationError, match="^n: must be a whole number$"):
        require_positive_int({"n": True}, "n")
    with pytest.raises(ValidationError, match="^n: must be positive$"):
        require_positive_int({"n": 0}, "n")


def test_require_email() -> None:
    assert require_email({"e": " Bo@Mail.Example "}, "e") == "bo@mail.example"
    with pytest.raises(ValidationError, match="^e: must not be blank$"):
        require_email({"e": ""}, "e")
    with pytest.raises(ValidationError, match="^e: must be an email address$"):
        require_email({"e": "bo@mail"}, "e")
