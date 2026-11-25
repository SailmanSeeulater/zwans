"""The XML feed:

    <?xml version="1.0" encoding="UTF-8"?>
    <feed shop="My shop" generated="2026-03-01T09:00:00Z">
      <item>
        <id>TEE-01-M</id>
        <item_group_id>TEE-01</item_group_id>
        <title>Logo tee (size: M)</title>
        ...
        <option name="size">M</option>
      </item>
    </feed>

Empty optional fields (sale_price, gtin) are left out rather than written empty.
"""

from shopdesk.feeds.items import FeedItem

FIELDS = (
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
)


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_xml(items: list[FeedItem], shop_name: str, generated: str) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<feed shop="{escape(shop_name)}" generated="{escape(generated)}">',
    ]
    for item in items:
        out.append("  <item>")
        for field in FIELDS:
            value = getattr(item, field)
            if value is None or value == "":
                continue
            out.append(f"    <{field}>{escape(str(value))}</{field}>")
        for name, value in item.options:
            out.append(f'    <option name="{escape(name)}">{escape(value)}</option>')
        out.append("  </item>")
    out.append("</feed>")
    return "\n".join(out) + "\n"
