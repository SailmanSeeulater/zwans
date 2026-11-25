"""The CSV feed: a header row, then one row per item. Empty optional fields are empty
cells; `options` reads like `colour=red;size=M`."""

import csv
import io

from shopdesk.feeds.items import FeedItem

COLUMNS = (
    "id",
    "item_group_id",
    "title",
    "description",
    "link",
    "price",
    "sale_price",
    "availability",
    "gtin",
    "brand",
    "product_type",
    "options",
)


def render_csv(items: list[FeedItem]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for item in items:
        writer.writerow([_cell(item, column) for column in COLUMNS])
    return buffer.getvalue()


def _cell(item: FeedItem, column: str) -> str:
    if column == "options":
        return item.options_text
    value = getattr(item, column)
    return "" if value is None else str(value)
