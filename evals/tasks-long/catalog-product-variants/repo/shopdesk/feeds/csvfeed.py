"""The CSV feed: a header row, then one row per item. Empty optional fields are empty
cells."""

import csv
import io

from shopdesk.feeds.items import FeedItem

COLUMNS = (
    "id",
    "title",
    "description",
    "link",
    "price",
    "sale_price",
    "availability",
    "gtin",
    "brand",
    "product_type",
)


def render_csv(items: list[FeedItem]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for item in items:
        writer.writerow(["" if getattr(item, c) is None else getattr(item, c) for c in COLUMNS])
    return buffer.getvalue()
