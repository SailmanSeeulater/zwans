"""Monthly budgets per category."""

from ledger.money import parse_amount as to_cents


class Budget:
    def __init__(self, limits: dict[str, str]) -> None:
        self.limits = {category: to_cents(limit) for category, limit in limits.items()}
        self.spent: dict[str, int] = {}

    def spend(self, category: str, amount: str) -> None:
        self.spent[category] = self.spent.get(category, 0) + to_cents(amount)

    def remaining(self, category: str) -> int:
        return self.limits.get(category, 0) - self.spent.get(category, 0)

    def over_budget(self) -> list[str]:
        return sorted(name for name in self.limits if self.remaining(name) < 0)
