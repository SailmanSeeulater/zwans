from shopapi.errors import ValidationError


def create_order(payload: dict) -> dict:
    if "customer_email" not in payload:
        raise ValidationError("customer_email", "is required")
    email = payload["customer_email"]
    if not isinstance(email, str):
        raise ValidationError("customer_email", "must be text")
    email = email.strip()
    if not email:
        raise ValidationError("customer_email", "must not be blank")
    local, _, domain = email.partition("@")
    if not local or "." not in domain:
        raise ValidationError("customer_email", "must be an email address")

    if "sku" not in payload:
        raise ValidationError("sku", "is required")
    sku = payload["sku"]
    if not isinstance(sku, str):
        raise ValidationError("sku", "must be text")
    sku = sku.strip()
    if not sku:
        raise ValidationError("sku", "must not be blank")

    if "quantity" not in payload:
        raise ValidationError("quantity", "is required")
    quantity = payload["quantity"]
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValidationError("quantity", "must be a whole number")
    if quantity <= 0:
        raise ValidationError("quantity", "must be positive")

    return {"customer_email": email.lower(), "sku": sku.upper(), "quantity": quantity}
