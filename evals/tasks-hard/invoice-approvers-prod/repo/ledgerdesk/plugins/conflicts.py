"""Conflicts of interest: you cannot approve an invoice you submitted, or one from a vendor
whose relationship you manage."""

from ledgerdesk.plugins import Plugin, register


@register("conflicts")
class Conflicts(Plugin):
    def check(self, ctx, request):
        if request.permission != "invoice.approve":
            return None
        invoice, username = request.invoice, request.user.username
        if invoice.submitted_by == username:
            return "submitted this invoice"
        if invoice.vendor.owner == username:
            return f"manages the vendor {invoice.vendor.name}"
        return None
