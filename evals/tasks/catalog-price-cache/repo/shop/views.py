"""Price tags for the product page."""

from shop.catalog import price

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def format_money(amount: int, currency: str) -> str:
    symbol = SYMBOLS.get(currency, currency + " ")
    if currency == "JPY":
        return f"{symbol}{amount:,}"
    return f"{symbol}{amount // 100:,}.{amount % 100:02d}"


def price_tag(sku: str, currency: str = "USD", quantity: int = 1) -> str:
    total = price(sku, currency=currency, quantity=quantity)
    tag = format_money(total, currency)
    if quantity > 1:
        tag += f" for {quantity}"
    return tag
