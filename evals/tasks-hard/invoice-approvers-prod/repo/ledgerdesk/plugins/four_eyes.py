"""Four eyes: nobody approves the same invoice twice, so each step is a different person."""

from ledgerdesk.plugins import Plugin, register


@register("four_eyes")
class FourEyes(Plugin):
    def check(self, ctx, request):
        if request.permission == "invoice.approve" and request.invoice.approved_by(
            request.user.username
        ):
            return "already approved an earlier step of this invoice"
        return None
