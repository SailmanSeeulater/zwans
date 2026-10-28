from shopapi.errors import ValidationError


def create_product(payload: dict) -> dict:
    record = {}
    for field in ("sku", "title"):
        if field not in payload:
            raise ValidationError(field, "is required")
        value = payload[field]
        if not isinstance(value, str):
            raise ValidationError(field, "must be text")
        value = value.strip()
        if not value:
            raise ValidationError(field, "must not be blank")
        record[field] = value

    if "price_cents" not in payload:
        raise ValidationError("price_cents", "is required")
    price = payload["price_cents"]
    if isinstance(price, bool) or not isinstance(price, int):
        raise ValidationError("price_cents", "must be a whole number")
    if price <= 0:
        raise ValidationError("price_cents", "must be positive")
    record["price_cents"] = price

    record["sku"] = record["sku"].upper()
    return record
