"""Split an amount into parts, e.g. an expense across cost centres."""

from books.money import Money


def allocate(amount: Money, weights: list[int]) -> list[Money]:
    """Split `amount` in proportion to `weights`, to the cent.

    The parts always add up to exactly `amount`. Each part is first rounded down to the
    cent; the cents left over go one each to the parts that lost the most in rounding
    (earlier parts first on a tie).
    """
    if not weights or any(weight < 0 for weight in weights) or sum(weights) == 0:
        raise ValueError("weights must be non-negative and not all zero")
    if amount < 0:
        raise ValueError("amount must not be negative")
    total_weight = sum(weights)
    cents = int(amount * 100)
    exact = [cents * weight / total_weight for weight in weights]
    parts = [int(share) for share in exact]
    leftover = cents - sum(parts)
    by_loss = sorted(range(len(weights)), key=lambda i: parts[i] - exact[i])
    for i in by_loss[:leftover]:
        parts[i] += 1
    return [part / 100 for part in parts]
