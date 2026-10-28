from shopapi.errors import ValidationError


def create_user(payload: dict) -> dict:
    if "name" not in payload:
        raise ValidationError("name", "is required")
    name = payload["name"]
    if not isinstance(name, str):
        raise ValidationError("name", "must be text")
    name = name.strip()
    if not name:
        raise ValidationError("name", "must not be blank")

    if "email" not in payload:
        raise ValidationError("email", "is required")
    email = payload["email"]
    if not isinstance(email, str):
        raise ValidationError("email", "must be text")
    email = email.strip()
    if not email:
        raise ValidationError("email", "must not be blank")
    local, _, domain = email.partition("@")
    if not local or "." not in domain:
        raise ValidationError("email", "must be an email address")
    email = email.lower()

    if "age" not in payload:
        raise ValidationError("age", "is required")
    age = payload["age"]
    if isinstance(age, bool) or not isinstance(age, int):
        raise ValidationError("age", "must be a whole number")
    if age <= 0:
        raise ValidationError("age", "must be positive")

    return {"name": name, "email": email, "age": age}
