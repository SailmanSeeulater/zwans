# billfold

Personal bookkeeping in one JSON file: accounts in several currencies, transactions,
imports from your bank, categorisation rules, monthly budgets, recurring entries,
reports, exports and backups. Run it with `python -m billfold --help`.

```
python -m billfold account add Checking --currency EUR --opening 1250
python -m billfold add Checking -42.80 --payee "REWE Markt" --category Food:Groceries
python -m billfold import csv Checking ~/Downloads/umsaetze.csv --profile eu-bank
python -m billfold rule add Netflix --if "payee~netflix" --category Subscriptions
python -m billfold budget set Food 2026-03 450
python -m billfold recurring add Checking "Landlord" -1100 monthly 2026-01-01 --category Rent
python -m billfold report monthly 2026-03
python -m billfold export qif checking.qif --account Checking
python -m billfold backup create
```

The data file is `--file` (default `$BILLFOLD_FILE`, else `billfold.json`).
`BILLFOLD_TODAY=2026-03-01` pins "today" for scripts and tests. Alerts are printed to
stderr and appended to `alerts.jsonl` next to the data file.

## How it works

**Accounts** have a name, a currency, a kind (checking, savings, credit, cash,
investment) and an opening balance. **Transactions** belong to one account; negative
amounts are money going out. A transaction can be **split** over several categories.
A **transfer** is two linked transactions; between accounts in different currencies the
received amount is converted with the stored exchange rates (or a rate you give).

**Categories** are written with colons, `Food:Groceries`, and a budget or report on
`Food` covers everything under it.

**Rules** categorise transactions that arrive without a category (from `add` or an
import). Conditions (`payee~netflix`, `memo^rent`, `amount=9.99`, `amount<20`,
`amount=10..20`, `account=Checking`, `payee/regex/`) must all hold; amounts in conditions
ignore the sign. The first matching rule by priority wins. Actions: set a category,
rename the payee, add tags, or split the transaction by percentages
(`--split Groceries=70 --split Household=30`).

**Budgets** are per category per month, in the base currency (`settings.base_currency`,
EUR unless changed); only accounts in the base currency count, transfers never do.
Spending is money out minus refunds. With `--rollover` what is left (or overspent)
carries into the next month. `budget allocate 2026-04 2000 Food=3 Rent=10 Fun=1` shares
an amount out over categories by weight and sets those budgets. When a change takes a
category over its budget for the month you get a `budget.exceeded` alert.

**Recurring entries** (weekly, fortnightly, monthly, quarterly, yearly) are booked by
`recurring run`, up to today or `--until`. A monthly entry started on the 31st stays on
the last day of shorter months. With `--instalments N` the amount is a total paid in N
parts, after which the entry stops.

**Exchange rates**: a rate `EUR USD 1.0825` on a day says one EUR buys 1.0825 USD. The
rate for a day is the latest one on or before it; if only USD->EUR is stored, EUR->USD
goes through it backwards. `rate import rates.csv` reads `date,base,quote,rate` files.

**Reports**: `monthly` (income, spending, net, by category, top payees, average spending
per day), `yearly` (a row per month, totals, average monthly spending, by top-level
category), `networth` (every account's balance on a day, converted into one currency)
and `budget`. Monthly and yearly reports cover one currency (the base currency unless
`--currency` says otherwise). Every report has `--json`.

**Search**: `billfold search coffee payee:acme cat:Food acct:Checking amount:9.99
amount>100 amount:10..20 since:2026-01-01 until:2026-03-31 #holiday` (all terms must
hold; amounts ignore the sign).

**Undo**: every change to transactions (add, edit, delete, split, transfer, import,
recurring run) can be undone, most recent first; the last 50 changes are kept in the
data file. `billfold history` lists them.

**Alerts**: `budget.exceeded` (category, month, currency, budget, spent, over_by) and,
after `billfold alert 500`, `transaction.large` for any transaction in the base currency
of at least that size (transaction, account, date, payee, currency, amount, threshold).
In Python, `book.on_alert(callback)` subscribes; every alert is an event dict with a
`type` key plus those fields.

**Imports**: CSV files through a profile saying which column is which (`default`:
`date,amount,payee,memo`; `debit-credit`: separate `debit` and `credit` columns;
`eu-bank`: semicolons, `dd.mm.yyyy` and decimal commas). Amounts may be written
`1,234.50`, `-12.00`, `(12.00)` or `12.00-` (both negative) and may carry a currency
sign. Bank statements in our bank's text format (see `billfold/importers/statement.py`)
are checked before anything is added: the entries must lead from the opening to the
closing balance, and the opening balance must match the account. Importing the same file
twice adds nothing the second time. An import is one undo step.

**Exports**: CSV (one row per transaction, or per piece of a split one, with a running
balance per account), JSON (accounts with balances, and all transactions) and QIF.

**Backups**: `backup create` writes `backups/billfold-YYYYmmdd-HHMMSS.tar.gz` next to the
data file, holding `book.json` (the data file as it would be saved) and `manifest.json`
(creation time, file version, a SHA-256 of `book.json`, and each account's balance and
number of transactions). `backup restore` checks the checksum and recomputes every
balance before writing anything, and refuses a backup that doesn't match.

**Reconcile**: `billfold reconcile Checking 1234.50 --clear txn-12 --clear txn-14` marks
transactions as cleared and compares the opening balance plus the cleared transactions
with the statement balance.

### Currencies

| code | places | | code | places |
|------|--------|-|------|--------|
| EUR  | 2      | | SEK  | 2      |
| USD  | 2      | | CAD  | 2      |
| GBP  | 2      | | JPY  | 0      |
| CHF  | 2      | |      |        |

The CLI and the text reports show amounts with thousands separators and the currency's
number of places: `1,234.50`, `-12.00`, `1,500` for yen.

### The data file

One JSON document with a `version`. Today's files are version 2; billfold still opens
version 1 files from the 0.x releases (one currency per file, accounts keyed by name)
and writes them back as the current version. The file also caches each account's
balance (with the transaction count it was computed from, so a stale cache is ignored)
and the undo history. The previous copy is kept as `billfold.json.bak`.

## Exact money (planned for 3.0)

Amounts are binary floats today, and it shows: three coffees at 0.10 make a balance of
0.30000000000000004, the JSON export writes numbers like that, splitting 100.00 three
ways loses a cent, and a budget of 19.99 doesn't match a rule for `amount=19.99`. In 3.0
money is exact. These are the rules:

1. **One type.** Every amount billfold hands back in Python is a `decimal.Decimal` with
   exactly the currency's number of places: `Decimal("12.50")` (not `Decimal("12.5")`)
   for euros, `Decimal("1500")` for yen. That covers transaction and split amounts,
   opening balances, `balance()`, budget lines, recurring entries, `convert()`, the
   reconcile result, every amount in the report objects, and the rows the importers read
   (`parse_statement`; `read_rows` doesn't know the account's currency, so its amounts are
   Decimals exactly as written). Exchange rates are Decimals too, exactly as given.
2. **Input.** The API takes amounts as `Decimal`, `int` or `str` in every form
   `parse_amount` reads (`"1,234.50"`, `"(12.00)"`, `"12.00-"`, `"€12.00"`...).
   `parse_amount` returns a `Decimal` exactly as written. A `float` is refused with
   `TypeError`, everywhere, including `parse_amount`. An amount with more places than its
   currency has (`"12.345"` euros, `"1.5"` yen) is refused with `MoneyError`, never
   rounded; in an import file it stops the import with an `ImportProblem` naming the line.
   Rates, budget weights and split percentages are read the same way (no floats) but
   aren't limited in places.
3. **Arithmetic is exact.** Balances, sums, report totals, budget spending, carried and
   remaining amounts, statement checks, reconcile differences and duplicate detection
   never round and never compare with a tolerance.
4. **Rounding happens only where a result can't be exact**, always to the currency's
   places and always as stated here:
   - *Conversion* (cross-currency transfers, `convert`, the net-worth report): multiply by
     the rate, or divide by the opposite rate when only that one is stored, then round
     once, half away from zero. The net-worth report converts each account's balance once
     (never transaction by transaction). Each line shows its converted balance rounded as
     above, but the total is the exact sum of the unrounded conversions, rounded once, so
     it can differ from the sum of the lines.
   - *Averages* (the monthly report's daily average, the yearly report's monthly average):
     the exact total divided, rounded once, half away from zero.
   - *Even shares* (`split_transaction` over a list of categories, and the instalments of
     a recurring entry): each part gets the total divided by the number of parts,
     rounded toward zero, and the minor units left over go one each to the first parts.
     100.00 over three categories is 33.34, 33.33, 33.33; 1000.00 in 12 instalments is
     four of 83.34 then eight of 83.33. Negative totals are shared the same way with the
     sign put back (-33.34, -33.33, -33.33).
   - *Weighted shares* (`budgets.allocate`, rule splits by percentage): each part gets
     its exact share rounded toward zero, and the leftover minor units go one each to the
     parts that lost the largest remainders, ties to the part listed first. Shares
     always add up to the total.
   - *Old files*, below.
5. **The data file** is written as version 3. Every amount in it (opening balances,
   transaction and split amounts, budgets, recurring entries, the large-transaction
   threshold, the cached balances, the amounts in the undo history) is a JSON string with
   exactly its currency's places: `"1234.50"`, `"-12.00"`, `"1500"`. Rates and split
   percentages are strings as given (`"1.0825"`). Version 1 and 2 files still open:
   every float in them, in every section, is read as its shortest repr (`0.1` is
   `"0.1"`) and rounded half away from zero to its currency's places, so old cached
   balances, budgets, recurring entries and undo history all come back exact. They are
   written as version 3 on the next save.
6. **Exports and alerts.** CSV and QIF write each amount (and the CSV running balance) as
   plain text with exactly the currency's places, a `.` and no thousands separators:
   `1234.50`, `-12.00`, `1500`. The JSON export writes every amount as a string in that
   form, and so do alert events, both for `on_alert` subscribers and in `alerts.jsonl`.
7. **Backups.** `book.json` is the data file exactly as saved, the manifest's balances are
   strings in the same form, and restore compares them exactly. Backups made by 2.x
   still restore.
8. **The CLI** reads amounts in every form `parse_amount` reads, so
   `billfold add Checking "(12.00)"` and `billfold add Checking "1,234.50"` work, and
   shows them as it does today. `--json` output writes every amount as a string in the
   export form.

## Python API

```python
from billfold import Book, FixedClock

book = Book.open("billfold.json", clock=FixedClock("2026-03-01"))   # or Book() in memory
book.add_account("Checking", currency="EUR", opening_balance="1250.00")
txn = book.add_transaction("Checking", "2026-03-02", "-42.80", payee="REWE",
                           category="Food:Groceries")
book.edit_transaction(txn.id, amount="-43.80")
book.split_transaction(txn.id, ["Food", "Household"])        # or {"Food": "-30.00", ...}
book.transfer("Checking", "Savings", "200.00", "2026-03-03")
book.balance("Checking"); book.balance("Checking", on=date(2026, 3, 2))
book.set_rate("EUR", "USD", "1.0825", "2026-03-01"); book.convert("10.00", "EUR", "USD")
book.add_rule("Netflix", ["payee~netflix"], category="Subscriptions")
book.budgets.set("Food", "2026-03", "450.00"); book.budgets.status("2026-03")
book.budgets.allocate("2000.00", {"Food": 3, "Rent": 10}, "2026-04")
book.recurring.add("Checking", "Landlord", "-1100.00", "monthly", "2026-01-01")
book.recurring.run(until=date(2026, 3, 31))
book.search("payee:acme amount>100"); book.undo()
book.on_alert(print); book.set_large_transaction_alert("500.00")
book.save()
```

Reports live in `billfold.reports` (`monthly_report`, `yearly_report`, `net_worth`,
`budget_report`, each with a `render_*` text form and a `to_dict` in its module),
exports in `billfold.exporters` (`csv_text`, `export_document`, `qif_text` and the
`export_*` file writers), imports in `billfold.importers` (`import_csv`, `read_rows`,
`import_statement`, `parse_statement`), backups in `billfold.backup` (`create_backup`,
`restore_backup`, `read_backup`) and reconciling in `billfold.reconcile`.

## Tests

`python -m pytest`. `tests/data/` holds data files written by earlier releases; they
must keep opening.
