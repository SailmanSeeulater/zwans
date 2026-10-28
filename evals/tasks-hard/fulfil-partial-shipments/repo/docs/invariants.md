# Invariants

Things that must be true after every operation, whatever happened before. Finance and the
warehouse rely on them; `tests/helpers.py` checks them after every test scenario.

## Stock

1. For every product, `reserved` is exactly the number of units that open orders still
   have to ship. Cancelled orders and shipped goods reserve nothing.
2. `0 <= reserved <= on_hand`.
3. `on_hand` is explained by the movements: received + restocked - shipped.
4. What left the warehouse for an order (the `ship` movements) is exactly what its
   invoices list.

## Billing

5. Every invoice lists exactly the goods that left the warehouse with it, at the order's
   prices; its subtotal is the sum of its lines and its total is
   subtotal - discount + shipping.
6. What we have invoiced for an order is always exactly what its shipped goods cost: their
   subtotal, less the order's discount on that subtotal (rounded half up), plus the
   shipping fee once anything has shipped. Shipping is charged once per order. Once
   everything has shipped, the invoices add up to the order total.

## Returns

7. Only goods that were shipped can be returned, and each unit only once.
8. The credit notes for an order add up to the returned goods' subtotal less the order's
   discount on it, so we never credit more than we invoiced for those goods. Shipping is
   never refunded.

## Reports

9. `sales(day)` counts the units that left the warehouse that day, and the invoices and
   credit notes issued that day.
10. `backlog()` lists every unit that is ordered and has not shipped yet, unless its order
    was cancelled.
