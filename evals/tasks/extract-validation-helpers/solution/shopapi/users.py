from shopapi.validation import require_email, require_positive_int, require_text


def create_user(payload: dict) -> dict:
    name = require_text(payload, "name")
    email = require_email(payload, "email")
    age = require_positive_int(payload, "age")
    return {"name": name, "email": email, "age": age}
