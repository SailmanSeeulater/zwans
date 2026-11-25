"""The maintenance job: run it from cron (``leafwiki maintain``) once a day or so.

It trims what grows without bound and removes what nothing uses any more:

* old revisions beyond ``keep_revisions`` per page (when that is not 0),
* recent-changes entries older than ``changes_retention_days``,
* outbox messages beyond ``outbox_limit``, oldest first,
* attachment contents no page refers to any more (left behind by detach and delete).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .wiki import Wiki


@dataclass
class MaintenanceReport:
    revisions_pruned: int = 0
    changes_trimmed: int = 0
    outbox_dropped: int = 0
    blobs_removed: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    def lines(self) -> list[str]:
        return [f"{key.replace('_', ' ')}: {value}" for key, value in self.to_dict().items()]

    @property
    def total(self) -> int:
        return sum(self.to_dict().values())


def prune_revisions(wiki: Wiki, keep: int) -> int:
    if keep <= 0:
        return 0
    pruned = 0
    for page in wiki.pages():
        extra = len(page.revisions) - keep
        if extra > 0:
            wiki._store_page(replace(page, revisions=page.revisions[extra:]))
            pruned += extra
    return pruned


def referenced_blobs(wiki: Wiki) -> set[str]:
    return {a.blob for page in wiki.pages() for a in page.attachments.values()}


def sweep_blobs(wiki: Wiki) -> int:
    keep = referenced_blobs(wiki)
    removed = 0
    for key in wiki.store.blob_keys():
        if key not in keep:
            wiki.store.remove_blob(key)
            removed += 1
    return removed


def run_maintenance(wiki: Wiki) -> MaintenanceReport:
    settings = wiki.settings
    report = MaintenanceReport()
    report.revisions_pruned = prune_revisions(wiki, settings.keep_revisions)
    report.changes_trimmed = wiki.changes.trim(wiki.clock(), settings.changes_retention_days)
    report.outbox_dropped = wiki.outbox_queue.trim(settings.outbox_limit)
    report.blobs_removed = sweep_blobs(wiki)
    return report
