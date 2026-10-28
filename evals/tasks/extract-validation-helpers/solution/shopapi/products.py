from shopapi.validation import require_positive_int, require_text


def create_product(payload: dict) -> dict:
    sku = require_text(payload, "sku")
    title = require_text(payload, "title")
    price = require_positive_int(payload, "price_cents")
    return {"sku": sku.upper(), "title": title, "price_cents": price}
