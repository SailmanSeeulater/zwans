"""Exchange rates from US dollars. Refreshed by the nightly job; fixed here for the demo."""

RATES = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 151.3,
}


class UnknownCurrency(Exception):
    pass


def convert(usd_cents: int, currency: str) -> int:
    """Convert an amount in US cents to the smallest unit of `currency`, rounded."""
    try:
        rate = RATES[currency]
    except KeyError:
        raise UnknownCurrency(currency) from None
    if currency == "JPY":  # yen have no cents
        return round(usd_cents / 100 * rate)
    return round(usd_cents * rate)
