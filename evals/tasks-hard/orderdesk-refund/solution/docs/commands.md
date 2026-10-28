# Commands

Every command that changes an order. Each one is permission-checked, validated, and
written to the audit log whatever the outcome. The `--role` option says whose permissions
apply (`clerk`, `manager` or `auditor`).

## place

```
orderdesk place --customer NAME --email ADDRESS --line SKU:QTY:PRICE [--line ...]
```

Places a new order and prints its id. The customer gets an order confirmation.

- Permission: `orders.place` (clerks, managers)
- Event: `order.placed`

## pay

```
orderdesk pay ORDER --amount AMOUNT [--method card|transfer|cash]
```

Records the payment for a placed order. We only take payment in full, so the amount must be
exactly the order total.

- Permission: `orders.pay` (clerks, managers)
- Event: `payment.captured`

## ship

```
orderdesk ship ORDER --carrier CARRIER --tracking NUMBER
```

Marks a paid order as shipped. The customer gets the tracking number.

- Permission: `orders.ship` (clerks, managers)
- Event: `order.shipped`

## cancel

```
orderdesk cancel ORDER --reason TEXT
```

Cancels an order that has not shipped yet. Anything the customer paid goes back to them,
which shows up as a refund in `orderdesk report` on the day of the cancellation. The
customer gets an email saying so.

- Permission: `orders.cancel` (managers)
- Event: `order.cancelled`

## refund

```
orderdesk refund ORDER --amount AMOUNT --reason TEXT
```

Gives back some or all of what the customer paid for an order (shipped or not), without
cancelling it: say an item arrived damaged. Several partial refunds are fine, but never more
in total than was paid; money already given back (by earlier refunds) is not given back again
if the order is cancelled later. Once everything paid has been refunded, the order's status
is `refunded`. Refunds show up in `orderdesk report` on the day they happen and come off the
customer's figures. The customer gets an email saying so.

- Permission: `orders.refund` (managers)
- Event: `order.refunded`

## note

```
orderdesk note ORDER TEXT
```

Adds an internal note to an order (at most 500 characters). Customers never see notes.

- Permission: `orders.note` (clerks, managers)
- Event: `note.added`
