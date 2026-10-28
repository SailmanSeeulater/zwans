"""Customer invoices."""

from dataclasses import dataclass, field

from books.money import ZERO, Money, parse_amount, percent_of, round_cents


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: int
    unit_price: Money

    @property
    def amount(self) -> Money:
        return round_cents(self.quantity * self.unit_price)


@dataclass
class Invoice:
    number: str
    customer: str
    lines: list[LineItem] = field(default_factory=list)
    discount_percent: str = "0"
    tax_percent: str = "0"

    def add(self, description: str, quantity: int, unit_price: str) -> None:
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        self.lines.append(LineItem(description, quantity, parse_amount(unit_price)))

    @property
    def subtotal(self) -> Money:
        return sum((line.amount for line in self.lines), ZERO)

    @property
    def discount(self) -> Money:
        return percent_of(self.subtotal, self.discount_percent)

    @property
    def taxable(self) -> Money:
        return self.subtotal - self.discount

    @property
    def tax(self) -> Money:
        return percent_of(self.taxable, self.tax_percent)

    @property
    def total(self) -> Money:
        return self.taxable + self.tax
