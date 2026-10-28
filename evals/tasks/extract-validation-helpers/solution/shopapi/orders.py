from shopapi.validation import require_email, require_positive_int, require_text


def create_order(payload: dict) -> dict:
    email = require_email(payload, "customer_email")
    sku = require_text(payload, "sku")
    quantity = require_positive_int(payload, "quantity")
    return {"customer_email": email, "sku": sku.upper(), "quantity": quantity}
