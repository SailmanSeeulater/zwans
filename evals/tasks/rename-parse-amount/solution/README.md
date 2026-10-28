# ledger

Keeps household accounts in whole cents. Every amount people type goes through
`ledger.money.parse_amount`, which understands `1,200.05`, `$3` and `(4.10)`.

```
python -m ledger.cli 12.50 "(2.25)"
```

Run the tests with `python -m pytest`.
