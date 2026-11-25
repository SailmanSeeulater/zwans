"""VAT. Prices in shopdesk are net. An invoice adds tax per tax class: the class's rate
times the class's net total, rounded half up once per class (not per line)."""

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from shopdesk.config import Settings
from shopdesk.models import InvoiceLine, TaxLine
from shopdesk.money import apply_rate


def tax_lines(lines: Iterable[InvoiceLine], settings: Settings) -> list[TaxLine]:
    nets: dict[str, int] = defaultdict(int)
    for line in lines:
        nets[line.tax_class] += line.net
    result = []
    for tax_class in sorted(nets):
        rate = settings.tax_rate(tax_class)
        result.append(TaxLine(tax_class, _rate_text(rate), nets[tax_class], apply_rate(nets[tax_class], rate)))
    return result


def _rate_text(rate: Decimal) -> str:
    return format(rate.normalize(), "f") if rate else "0"


def rate_percent(rate: str) -> str:
    """"0.20" -> "20%", "0.055" -> "5.5%"."""
    value = (Decimal(rate) * 100).normalize()
    return f"{format(value, 'f')}%"
