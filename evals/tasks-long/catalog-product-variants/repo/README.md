# shopdesk

The back office of a small shop: the catalog, prices and discounts, stock in several
warehouses, carts and orders, invoices, the product feed for the comparison sites,
supplier price files, search for the shop front, low-stock alerts and the reports we look
at on Monday mornings. Python 3.12, no dependencies.

```
python -m shopdesk category add kitchen Kitchen
python -m shopdesk product add MUG-01 "Blue mug" --price 12.50 --category kitchen --barcode 5012345678900 --reorder-level 5
python -m shopdesk warehouse add MAIN "Main warehouse"
python -m shopdesk receive MUG-01 40 --warehouse MAIN --ref PO-1001
python -m shopdesk cart new                       # prints C0001
python -m shopdesk cart add C0001 MUG-01 2
python -m shopdesk checkout C0001 --customer "Ann Lee"
python -m shopdesk invoice create SO-000001
python -m shopdesk report sales --from 2026-03-01
python -m shopdesk feed xml --out feed.xml
```

Everything lives in one JSON data file (`--db`, default `shop.json`). `SHOPDESK_NOW`
(e.g. `2026-03-01T09:00:00Z`) fixes the clock for scripts and tests.

As a library:

```python
from shopdesk import Shop

shop = Shop.open("shop.json")
shop.add_product("MUG-01", "Blue mug", 1250, category="kitchen", reorder_level=5)
shop.receive("MUG-01", "MAIN", 40)
cart = shop.new_cart()
shop.cart_add(cart, "MUG-01", 2)
order = shop.checkout(cart, "Ann Lee")
shop.save()
```

## How it fits together

`shopdesk/shop.py` builds every service over one `ShopData` and wires them to an event
bus; the CLI and library users go through the `Shop`. The services:

| package / module       | what                                                              |
|------------------------|-------------------------------------------------------------------|
| `catalog/`             | products and the category tree                                    |
| `pricing/`             | price lists, discounts, and the engine that prices a cart line    |
| `stock/`               | warehouses, the stock ledger, low-stock alerts                     |
| `sales/`               | carts, checkout and orders, invoices and VAT                      |
| `search/`              | the search index and facet counts                                 |
| `feeds/`               | the product feed, as XML and CSV                                  |
| `importers/`           | supplier price files                                              |
| `reports/`             | sales and stock reports                                           |
| `store/`               | the data file: encoding, upgrades from old versions, backups      |
| `notify.py`            | the outbox of notifications for the warehouse and the packers     |
| `audit.py`             | the audit log                                                     |
| `cli/`                 | the command line                                                  |

## The rules

**Money** is in whole cents everywhere in the code and the data file; the CLI takes and
prints amounts like `12.50`. Prices are net (before VAT).

**SKUs** are upper case, 1-40 letters, digits, `.`, `-` or `_`. **Barcodes** are GTINs
(8, 12, 13 or 14 digits with a valid check digit) and unique across the catalog.

**Prices.** A cart can be priced with a price list (`trade`, `staff`, ...): a SKU on the
list costs the list price, anything else its normal price. Each cart line then gets the
single best discount it qualifies for (discounts never stack): automatic discounts apply
by themselves, the others only when their code is entered. A discount targets every
product, a category (including the categories below it) or one product, may need a
minimum quantity on the line, and may run between two dates. Percentage discounts are
rounded half up per line.

**Stock** is never stored. It is the sum of the moves in the ledger for a SKU in a
warehouse: receive, sale, return, adjust, count (sets stock to what was counted) and
transfer. Stock can't go below zero in any warehouse. Checkout picks from the
warehouses in priority order (or only from the one asked for) and either picks every
line or nothing. Cancelling an order puts the stock back where it came from; invoiced
orders can't be cancelled.

**Low-stock alerts.** An item with a reorder level above zero gets one alert when its
stock across all warehouses falls to the reorder level or below. It stays open until
stock rises above the level, and the next fall raises a new one. A raised alert also
puts a `stock.low` notification in the outbox.

**Invoices** carry one line per order line (SKU, EAN, description, quantity, unit price,
discount, net). VAT is added per tax class, rounded half up once per class.

**Search** returns products, best match first, with facet counts (`category`, `brand`,
`price` band, `in_stock`) over the results. Filters: category (with its subcategories),
brand, in stock, price range.

**The feed** lists active products for the comparison sites, as XML (`feed xml`) or CSV
(`feed csv`), with id, title, description, link, price, sale price (when an automatic
discount lowers the price of one unit today), availability, GTIN, brand and product type
(the category path).

**Supplier files** are CSV (comma or semicolon) with a header; common column names
(`ean`, `rrp`, `title`, ...) are understood. A known SKU updates the product with the
columns the file has, a new SKU becomes a product (it needs a name and a price). Bad
rows are reported by line and skipped. `--dry-run` changes nothing.

**Reports.** Sales (per product, per top-level category, per day; cancelled orders don't
count, revenue is net of discounts), stock per warehouse, and stock valuation at cost.

**The data file** carries a `format` and a `version`. shopdesk opens every earlier
version (`store/migrations.py` upgrades them) and writes the current one. Backups
(`backup create`, `backup restore`) must restore any file shopdesk can open.

## Product variants

We are adding variants: the shop now sells clothes in sizes and colours, and mugs in
several glazes. This is the agreed design.

- A product has one or more **variants**. Each variant is the thing actually sold and
  stocked: it has its own SKU, its options (any named options, such as
  `{"size": "M", "colour": "red"}`), and optionally its own price, barcode and reorder
  level. A variant without a price of its own costs the product's price; without a
  reorder level of its own it uses the product's.
- Variant SKUs follow the SKU rules and are unique across the shop: no two variants
  share one, and a variant can't take another product's SKU. Barcodes are unique across
  all variants. Two variants of one product can't have the same options.
- `shop.add_product(sku, name, price, ...)` without variants creates a product with one
  variant whose SKU is the product's SKU, with no options and the product's barcode.
  `shop.add_product(..., variants=[...])` takes dicts with `sku`, `options`, and
  optionally `price`, `barcode` and `reorder_level`, and the product gets exactly those
  variants. `shop.add_variant(product_sku, sku, options, price=None, barcode=None,
  reorder_level=None)` adds one, `shop.update_variant(sku, **changes)` changes its
  `price`, `barcode`, `reorder_level` or `options` (`None` takes away its own price or
  reorder level), and `shop.remove_variant(sku)` removes one; removing a product's last
  variant, or a variant with stock, is refused with a `ShopError`.
- `shop.product(sku)` takes a product SKU or a variant SKU and returns the product;
  `product.variants` lists its variants (`sku`, `options`, `price`, `barcode`,
  `reorder_level`) in the order they were added. `shop.variant(sku)` returns one variant.
- Everything that takes a SKU to sell, stock or price something (carts, stock moves,
  counts, transfers, `shop.stock`, `shop.price_of`, barcode lookup, the CLI) takes a
  variant SKU. A product SKU that isn't also one of its variants' SKUs can't be sold or
  stocked: using it raises `UnknownSku`.
- **Stock and alerts** are per variant. Each variant gets its own low-stock alert and
  `stock.low` notification, against its own reorder level; both carry the variant's SKU,
  its stock and its reorder level (the notification also its stock per warehouse).
  Alerts are rechecked when a variant's reorder level changes, or the product's.
- **Prices.** For a variant, a price list's entry for the variant SKU wins, then its entry
  for the product SKU, then the variant's own price, then the product's price.
  Discounts that target a product apply to all of its variants; category discounts go by
  the product's category.
- **Names.** Wherever a variant is shown by name (cart lines, order lines, invoice lines,
  feed titles, the stock report, the sales report by variant, notifications) it is the
  product name followed by the options in brackets, sorted by option name:
  `Logo tee (colour: red, size: M)`. A variant with no options shows just the product
  name.
- **Orders and invoices** have one line per variant. Order and invoice lines carry the
  variant SKU as `sku` and the product's SKU as `product_sku`; the invoice line's EAN is
  the variant's barcode.
- **Search** still returns one hit per product. It also finds a product by a variant's
  SKU, barcode or option values. A product is in stock when any of its variants is; the
  price filters, price sort and price facet use the product's lowest variant price.
  Facets get an `options` entry: for each option name, how many of the results have a
  variant with each value, e.g. `facets["options"] == {"size": {"M": 2, "L": 1}}`.
  `shop.search(..., options={"size": "M"})` keeps the products that have a variant with
  all the given options (CLI: `search --option size=M`).
- **The feed** has one item per variant of every active product, in product SKU order
  and then variant order. Each item's `id` is the variant SKU and its `item_group_id` the
  product SKU (single-variant products included); price, sale price, availability (the
  variant's own stock) and GTIN are the variant's. The CSV feed gets `item_group_id` and
  `options` columns (`colour=red;size=M`, sorted by name, empty for none); each XML
  `<item>` gets `<item_group_id>` and one `<option name="colour">red</option>` per option,
  sorted by name.
- **Supplier files** may have `parent_sku` and `options` (`size=M;colour=red`) columns. A
  row with a `parent_sku` is a variant of that product, with the row's options, price and
  barcode: a new SKU is added to the product as a variant (if the product doesn't exist
  yet, it is created from that row's name, price, category, brand and cost, and the row
  then needs a name and a price); an existing variant gets the row's price and barcode.
  A row without `parent_sku` whose SKU is a variant of another product updates that
  variant's price and barcode. Otherwise rows work as before. The import result lists
  each row under its own SKU, as before.
- **Reports.** The sales report stays one row per product, summing all its variants
  (`sku` and `name` are the product's); `sales_report(shop, ..., by_variant=True)` (CLI:
  `report sales --by-variant`) gives one row per variant SKU instead. The stock report
  has one row per variant; the valuation stays one row per product, counting the stock of
  all its variants at the product's cost.
- **Old data.** Files written before variants (any version) open with every product as a
  single-variant product whose variant SKU is the old SKU and which keeps the old
  barcode, so everything that worked keeps working, and the lines of their orders and
  invoices get `product_sku` equal to their `sku`. Backups of old and new files both restore.
- **CLI.** `variant add PRODUCT SKU --option size=M --option colour=red [--price 14.00]
  [--barcode ...] [--reorder-level N]`, `variant remove SKU`; `product show` lists each
  variant with its SKU, options, price and stock.

## Tests

`python -m pytest`. `tests/data/` holds data files written by earlier releases; they
must keep opening.
