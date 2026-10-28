"""Business hours for contractors.

Contractors may only act on weekdays during business hours *in their own local time*
(their `utc_offset` in the directory). The hours come from the `[business_hours]` table:
`start` (inclusive) and `end` (exclusive), whole hours, 9 and 17 when not configured.
Employees and service accounts are not restricted.
"""

from ledgerdesk.clock import local
from ledgerdesk.plugins import Plugin, register


@register("business_hours")
class BusinessHours(Plugin):
    def check(self, ctx, request):
        user = request.user
        if not user.is_contractor:
            return None
        settings = ctx.config.get("business_hours", {})
        start, end = settings.get("start", 9), settings.get("end", 17)
        when = local(request.at, user.utc_offset)
        if when.weekday() >= 5:
            return f"contractor, and it is the weekend for them ({when:%a %H:%M})"
        if not start <= when.hour < end:
            return f"contractor, outside business hours ({when:%a %H:%M} local)"
        return None
