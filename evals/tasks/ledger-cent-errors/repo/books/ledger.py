"""A double-entry ledger. Every entry's debits must equal its credits."""

from dataclasses import dataclass

from books.money import ZERO, Money, format_amount


class UnbalancedEntry(Exception):
    pass


@dataclass(frozen=True)
class Line:
    account: str
    debit: Money = ZERO
    credit: Money = ZERO


@dataclass(frozen=True)
class Entry:
    memo: str
    lines: tuple[Line, ...]


class Ledger:
    def __init__(self) -> None:
        self.entries: list[Entry] = []

    def post(self, memo: str, lines: list[Line]) -> Entry:
        if len(lines) < 2:
            raise UnbalancedEntry(f"{memo}: an entry needs at least two lines")
        for line in lines:
            if line.debit < ZERO or line.credit < ZERO:
                raise ValueError(f"{memo}: negative amount on {line.account}")
            if (line.debit == ZERO) == (line.credit == ZERO):
                raise ValueError(f"{memo}: {line.account} needs a debit or a credit")
        debits = sum((line.debit for line in lines), ZERO)
        credits = sum((line.credit for line in lines), ZERO)
        if debits != credits:
            raise UnbalancedEntry(
                f"{memo}: debits {format_amount(debits)} != credits {format_amount(credits)}"
            )
        entry = Entry(memo, tuple(lines))
        self.entries.append(entry)
        return entry

    def accounts(self) -> list[str]:
        return sorted({line.account for entry in self.entries for line in entry.lines})

    def balance(self, account: str) -> Money:
        """Debits minus credits."""
        total = ZERO
        for entry in self.entries:
            for line in entry.lines:
                if line.account == account:
                    total += line.debit - line.credit
        return total

    def trial_balance(self) -> Money:
        """The sum of every account's balance. Always zero for correct books."""
        return sum((self.balance(account) for account in self.accounts()), ZERO)
