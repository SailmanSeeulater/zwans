"""The checks every payload handler shares. Each raises ValidationError naming the field."""

from shopapi.errors import ValidationError


def require_text(payload: dict, field: str) -> str:
    if field not in payload:
        raise ValidationError(field, "is required")
    value = payload[field]
    if not isinstance(value, str):
        raise ValidationError(field, "must be text")
    value = value.strip()
    if not value:
        raise ValidationError(field, "must not be blank")
    return value


def require_positive_int(payload: dict, field: str) -> int:
    if field not in payload:
        raise ValidationError(field, "is required")
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(field, "must be a whole number")
    if value <= 0:
        raise ValidationError(field, "must be positive")
    return value


def require_email(payload: dict, field: str) -> str:
    value = require_text(payload, field)
    local, _, domain = value.partition("@")
    if not local or "." not in domain:
        raise ValidationError(field, "must be an email address")
    return value.lower()
