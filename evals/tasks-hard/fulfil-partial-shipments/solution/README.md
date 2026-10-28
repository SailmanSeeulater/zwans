# fulfil

Orders, stock, invoices and returns for a small web shop.

```python
from fulfil import Shop

shop = Shop()
shop.add_product("MUG-01", "Blue mug", 950)       # prices in cents
shop.receive("MUG-01", 20)
order = shop.place_order("alice", {"MUG-01": 2}, coupon="SPRING15")   # reserves stock
invoice = shop.ship(order.id, {"MUG-01": 1})      # part of it leaves, invoice issued
invoice = shop.ship(order.id)                     # the rest leaves, invoice issued
shop.return_items(order.id, "MUG-01", 1)          # restocked, credit note issued
```

- `fulfil/shop.py`: `Shop`, where orders, stock and billing change together.
- `fulfil/orders.py`: orders and their statuses.
- `fulfil/inventory.py`: on hand / reserved / available, and the movement log.
- `fulfil/billing.py`: invoices, credit notes, discounts.
- `fulfil/reports.py`: sales per day, backlog, stock.
- `docs/invariants.md`: what must always hold. Read it before changing anything.

Tests: `python -m pytest`.
