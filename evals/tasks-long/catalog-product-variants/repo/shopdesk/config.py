"""Shop settings, kept in the data file under "settings" and changed with
`shopdesk settings set KEY VALUE`."""

from dataclasses import asdict, dataclass, field, fields
from decimal import Decimal, InvalidOperation
from typing import Any

from shopdesk.errors import InvalidInput

DEFAULT_TAX_RATES = {"standard": "0.20", "reduced": "0.05", "zero": "0"}


@dataclass
class Settings:
    shop_name: str = "My shop"
    currency: str = "GBP"
    base_url: str = "https://shop.example.com"
    # upper bounds of the search price bands, in cents: 0-10, 10-25, 25-50, 50+
    price_bands: list[int] = field(default_factory=lambda: [1000, 2500, 5000])
    tax_rates: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TAX_RATES))
    feed_title_limit: int = 150
    invoice_prefix: str = "INV"
    order_prefix: str = "SO"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in raw.items() if k in known})
        settings.validate()
        return settings

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise InvalidInput(f"Currency must be a three-letter code, not {self.currency!r}.")
        if sorted(self.price_bands) != list(self.price_bands) or any(
            b <= 0 for b in self.price_bands
        ):
            raise InvalidInput("Price bands must be positive and ascending.")
        for tax_class, rate in self.tax_rates.items():
            try:
                value = Decimal(rate)
            except InvalidOperation:
                raise InvalidInput(f"Tax rate for {tax_class} is not a number.") from None
            if not 0 <= value < 1:
                raise InvalidInput(f"Tax rate for {tax_class} must be between 0 and 1.")
        if self.feed_title_limit < 10:
            raise InvalidInput("Feed titles need at least 10 characters.")

    def tax_rate(self, tax_class: str) -> Decimal:
        try:
            return Decimal(self.tax_rates[tax_class])
        except KeyError:
            raise InvalidInput(f"Unknown tax class {tax_class!r}.") from None

    def set(self, key: str, value: str) -> None:
        if key == "price_bands":
            try:
                self.price_bands = [int(part) for part in value.split(",")]
            except ValueError:
                raise InvalidInput("price_bands is a comma-separated list of cents.") from None
        elif key == "feed_title_limit":
            self.feed_title_limit = int(value)
        elif key.startswith("tax_rates."):
            self.tax_rates[key.removeprefix("tax_rates.")] = value
        elif key in ("shop_name", "currency", "base_url", "invoice_prefix", "order_prefix"):
            setattr(self, key, value.upper() if key == "currency" else value)
        else:
            raise InvalidInput(f"No setting {key!r}.")
        self.validate()


def band_labels(bands: list[int]) -> list[str]:
    """[1000, 2500, 5000] -> ["0-10", "10-25", "25-50", "50+"]"""
    labels = []
    low = 0
    for upper in bands:
        labels.append(f"{_whole(low)}-{_whole(upper)}")
        low = upper
    labels.append(f"{_whole(low)}+")
    return labels


def band_of(price: int, bands: list[int]) -> str:
    labels = band_labels(bands)
    for label, upper in zip(labels, bands, strict=False):
        if price < upper:
            return label
    return labels[-1]


def _whole(cents: int) -> str:
    return str(cents // 100) if cents % 100 == 0 else f"{cents / 100:.2f}"
