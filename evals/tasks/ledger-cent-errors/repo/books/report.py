"""A printable trial balance."""

from books.ledger import Ledger
from books.money import ZERO, format_amount


def trial_balance_report(ledger: Ledger) -> str:
    rows = [f"{'Account':<24}{'Debit':>12}{'Credit':>12}"]
    total_debit = total_credit = ZERO
    for account in ledger.accounts():
        balance = ledger.balance(account)
        if balance >= ZERO:
            debit, credit = balance, ZERO
        else:
            debit, credit = ZERO, -balance
        total_debit += debit
        total_credit += credit
        rows.append(f"{account:<24}{format_amount(debit):>12}{format_amount(credit):>12}")
    rows.append(f"{'Total':<24}{format_amount(total_debit):>12}{format_amount(total_credit):>12}")
    return "\n".join(rows)
