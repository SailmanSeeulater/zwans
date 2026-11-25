"""Invoices, one per order. Each line shows the SKU, the EAN (our trade customers scan
them in), the description from the order, quantity, unit price, discount and net; tax is
added per tax class at the bottom."""

from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock, day
from shopdesk.config import Settings
from shopdesk.errors import InvalidInput
from shopdesk.events import EventBus
from shopdesk.models import Invoice, InvoiceLine, ShopData
from shopdesk.money import format_money
from shopdesk.sales.orders import OrderDesk
from shopdesk.sales.tax import rate_percent, tax_lines


class Invoicing:
    def __init__(
        self,
        data: ShopData,
        catalog: ProductCatalog,
        orders: OrderDesk,
        settings: Settings,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._data = data
        self._catalog = catalog
        self._orders = orders
        self._settings = settings
        self._bus = bus
        self._clock = clock

    def issue(self, order_number: str) -> Invoice:
        order = self._orders.get(order_number)
        if order.status == "cancelled":
            raise InvalidInput(f"Order {order.number} is cancelled.")
        if order.invoice is not None:
            raise InvalidInput(f"Order {order.number} already has invoice {order.invoice}.")
        lines = []
        for line in order.lines:
            product = self._catalog.get(line.product_sku)
            variant = product.find_variant(line.sku)
            lines.append(
                InvoiceLine(
                    sku=line.sku,
                    gtin=variant.barcode if variant else None,
                    description=line.name,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    discount=line.discount,
                    tax_class=product.tax_class,
                    product_sku=product.sku,
                )
            )
        invoice = Invoice(
            number=self._next_number(),
            order=order.number,
            issued_at=self._clock(),
            customer=order.customer,
            lines=lines,
            taxes=tax_lines(lines, self._settings),
        )
        self._data.invoices[invoice.number] = invoice
        self._orders.mark_invoiced(order.number, invoice.number)
        self._bus.publish("invoice.issued", number=invoice.number, order=order.number)
        return invoice

    def _next_number(self) -> str:
        """INV-2026-0001: the counter starts again every year, as the accountant wants."""
        year = self._clock()[:4]
        sequence = self._data.next_id(f"invoice-{year}")
        return f"{self._settings.invoice_prefix}-{year}-{sequence:04d}"

    def get(self, number: str) -> Invoice:
        try:
            return self._data.invoices[number.strip().upper()]
        except KeyError:
            raise InvalidInput(f"No invoice {number!r}.") from None

    def all(self) -> list[Invoice]:
        return sorted(self._data.invoices.values(), key=lambda i: i.number)


def render_invoice(invoice: Invoice, settings: Settings) -> str:
    money = format_money
    out = [
        f"{settings.shop_name}",
        f"Invoice {invoice.number}  (order {invoice.order})",
        f"Date: {day(invoice.issued_at)}",
        f"Customer: {invoice.customer}",
        "",
        f"{'SKU':<14} {'EAN':<14} {'Description':<36} {'Qty':>4} {'Unit':>9} {'Disc':>8} {'Net':>10}",
    ]
    for line in invoice.lines:
        out.append(
            f"{line.sku:<14} {line.gtin or '':<14} {line.description[:36]:<36} {line.qty:>4} "
            f"{money(line.unit_price):>9} {money(line.discount):>8} {money(line.net):>10}"
        )
    out.append("")
    out.append(f"{'Net total':>60} {money(invoice.net_total):>30}")
    for tax in invoice.taxes:
        label = f"VAT {rate_percent(tax.rate)} on {money(tax.net)}"
        out.append(f"{label:>60} {money(tax.tax):>30}")
    out.append(f"{'Total ' + settings.currency:>60} {money(invoice.gross_total):>30}")
    return "\n".join(out) + "\n"
