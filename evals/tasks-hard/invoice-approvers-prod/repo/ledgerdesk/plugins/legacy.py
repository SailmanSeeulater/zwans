"""Legacy superusers: members of the `admins` group hold the controller role.

Kept for the old admin tooling. Do not enable this anywhere real.
"""

from ledgerdesk.plugins import Plugin, register


@register("legacy_superuser")
class LegacySuperuser(Plugin):
    def grants(self, ctx, user, at):
        if user.username in ctx.directory.members("admins"):
            return ["controller"]
        return []
