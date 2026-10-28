"""Reports for the finance team.

`approval_matrix` is a planning aid: for every pending invoice it lists the people whose
*own* roles (group bindings only) allow them to approve that amount. It deliberately
ignores delegations, absences and every plugin rule, so it shows who could approve in
principle, not who may approve at a given moment. Use ledgerdesk.policy.engine for that.
"""

from dataclasses import dataclass
from decimal import Decimal

from ledgerdesk.context import Context
from ledgerdesk.policy.engine import amount_eur
from ledgerdesk.policy.roles import direct_roles


@dataclass
class MatrixRow:
    invoice_id: str
    vendor: str
    amount_eur: Decimal
    approvers: list[str]


def approval_matrix(ctx: Context) -> list[MatrixRow]:
    rows = []
    for invoice in ctx.invoices.pending():
        amount = amount_eur(ctx, invoice)
        approvers = []
        for user in ctx.directory.users():
            for role_name in direct_roles(user.username, ctx.bindings, ctx.directory):
                role = ctx.roles.get(role_name)
                if "invoice.approve" not in role.permissions:
                    continue
                if role.limit_eur is None or role.limit_eur >= amount:
                    approvers.append(user.username)
                    break
        rows.append(MatrixRow(invoice.id, invoice.vendor.name, amount, approvers))
    return rows


def spend_by_cost_center(ctx: Context) -> dict[str, Decimal]:
    """Pending spend per cost center, in euros."""
    totals: dict[str, Decimal] = {}
    for invoice in ctx.invoices.pending():
        totals[invoice.cost_center] = totals.get(invoice.cost_center, Decimal(0)) + amount_eur(
            ctx, invoice
        )
    return dict(sorted(totals.items()))


def format_matrix(rows: list[MatrixRow]) -> str:
    lines = []
    for row in rows:
        lines.append(f"{row.invoice_id}  {row.vendor:<22} {row.amount_eur:>12,} EUR")
        lines.append("    " + (", ".join(row.approvers) or "(nobody)"))
    return "\n".join(lines)
