"""Command line for ledgerdesk.

    python -m ledgerdesk who-can INV-2291                     who may approve it now
    python -m ledgerdesk who-can INV-2291 --at 2025-11-03T10:00 --explain
    python -m ledgerdesk check mkoch INV-2291                 may mkoch approve it now?
    python -m ledgerdesk invoices                             list pending invoices
    python -m ledgerdesk roles mkoch                          what mkoch holds now
    python -m ledgerdesk matrix                               planning overview (see reports.py)

The environment comes from LEDGERDESK_ENV (see ledgerdesk.config.loader).
"""

import argparse
import sys
from datetime import datetime

from ledgerdesk import clock
from ledgerdesk.context import Context, build_context
from ledgerdesk.policy.engine import Request, amount_eur, decide, holdings, who_can
from ledgerdesk.reports import approval_matrix, format_matrix, spend_by_cost_center


def _at(args: argparse.Namespace) -> datetime:
    return clock.parse_instant(args.at) if args.at else clock.now()


def cmd_who_can(ctx: Context, args: argparse.Namespace) -> int:
    at = _at(args)
    invoice = ctx.invoices.get(args.invoice)
    print(f"# {invoice.id}, {args.permission}, env={ctx.env}, at {clock.describe(at)}")
    print(f"# total {invoice.total} = {amount_eur(ctx, invoice):,} EUR")
    decisions = who_can(ctx, args.permission, invoice.id, at)
    allowed = [d for d in decisions if d.allowed]
    for decision in allowed:
        print(f"{decision.username:<12} {decision.via}".rstrip())
    if not allowed:
        print("# nobody")
    if args.explain:
        for decision in decisions:
            if not decision.allowed and decision.reason != f"no role grants {args.permission}":
                print(f"# not {decision.username}: {decision.reason}")
    return 0


def cmd_check(ctx: Context, args: argparse.Namespace) -> int:
    at = _at(args)
    user = ctx.directory.user(args.username)
    invoice = ctx.invoices.get(args.invoice)
    decision = decide(ctx, Request(user, args.permission, invoice, at))
    verdict = "yes" if decision.allowed else f"no: {decision.reason}"
    print(f"{user.username} {args.permission} {invoice.id} at {clock.describe(at)}: {verdict}")
    return 0 if decision.allowed else 1


def cmd_invoices(ctx: Context, args: argparse.Namespace) -> int:
    for invoice in ctx.invoices.pending():
        print(
            f"{invoice.id}  {invoice.vendor.name:<22} {invoice.total!s:>16}"
            f"  step {invoice.next_step}  submitted by {invoice.submitted_by}"
        )
    return 0


def cmd_roles(ctx: Context, args: argparse.Namespace) -> int:
    at = _at(args)
    user = ctx.directory.user(args.username)
    for holding in holdings(ctx, user, at):
        extra = f" ({holding.detail})" if holding.detail else ""
        print(f"{holding.role:<16} {holding.source}{extra}")
    return 0


def cmd_matrix(ctx: Context, args: argparse.Namespace) -> int:
    print(format_matrix(approval_matrix(ctx)))
    print()
    for cost_center, total in spend_by_cost_center(ctx).items():
        print(f"{cost_center}  {total:>12,} EUR")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ledgerdesk")
    sub = p.add_subparsers(dest="command", required=True)

    who = sub.add_parser("who-can", help="list who may act on an invoice")
    who.add_argument("invoice")
    who.add_argument("--permission", default="invoice.approve")
    who.add_argument("--at", help="the instant to evaluate, ISO 8601 (default: now)")
    who.add_argument("--explain", action="store_true", help="also say why others may not")
    who.set_defaults(run=cmd_who_can)

    check = sub.add_parser("check", help="may one user act on an invoice?")
    check.add_argument("username")
    check.add_argument("invoice")
    check.add_argument("--permission", default="invoice.approve")
    check.add_argument("--at", help="the instant to evaluate, ISO 8601 (default: now)")
    check.set_defaults(run=cmd_check)

    invoices = sub.add_parser("invoices", help="list pending invoices")
    invoices.set_defaults(run=cmd_invoices)

    roles = sub.add_parser("roles", help="list the roles a user holds")
    roles.add_argument("username")
    roles.add_argument("--at", help="the instant to evaluate, ISO 8601 (default: now)")
    roles.set_defaults(run=cmd_roles)

    matrix = sub.add_parser("matrix", help="planning overview of pending invoices")
    matrix.set_defaults(run=cmd_matrix)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        ctx = build_context()
        return args.run(ctx, args)
    except Exception as exc:  # report, don't dump a traceback on finance staff
        print(f"ledgerdesk: {exc}", file=sys.stderr)
        return 2
