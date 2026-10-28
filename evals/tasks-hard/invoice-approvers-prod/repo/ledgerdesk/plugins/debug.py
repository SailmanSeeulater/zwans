"""Debug grants: hand out the senior approver role to the users listed in
`debug.grant_senior`, to try things out without editing the directory."""

from ledgerdesk.plugins import Plugin, register


@register("debug_grants")
class DebugGrants(Plugin):
    def grants(self, ctx, user, at):
        if user.username in ctx.config.get("debug", {}).get("grant_senior", []):
            return ["senior_approver"]
        return []
