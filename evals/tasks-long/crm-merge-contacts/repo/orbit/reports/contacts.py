"""Who is in the CRM: counts of contacts by owner, source, company and tag."""

from collections import Counter
from dataclasses import dataclass, field

from orbit.reports.tables import counts_table


@dataclass
class ContactSummary:
    total: int = 0
    active: int = 0
    archived: int = 0
    never_contacted: int = 0
    without_company: int = 0
    by_owner: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    by_company: dict[str, int] = field(default_factory=dict)
    by_tag: dict[str, int] = field(default_factory=dict)


def _sorted(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def contact_summary(crm) -> ContactSummary:
    companies = {row["id"]: row["name"] for row in crm.store.rows("companies")}
    summary = ContactSummary()
    owners: Counter = Counter()
    sources: Counter = Counter()
    by_company: Counter = Counter()
    tags: Counter = Counter()
    for row in crm.store.rows("contacts"):
        summary.total += 1
        if row.get("status", "active") == "active":
            summary.active += 1
        else:
            summary.archived += 1
        if not row.get("last_contacted_at"):
            summary.never_contacted += 1
        owners[row.get("owner", "")] += 1
        sources[row.get("source", "")] += 1
        if row.get("company_id"):
            by_company[companies.get(row["company_id"], row["company_id"])] += 1
        else:
            summary.without_company += 1
        tags.update(row.get("tags", []))
    summary.by_owner = _sorted(owners)
    summary.by_source = _sorted(sources)
    summary.by_company = _sorted(by_company)
    summary.by_tag = _sorted(tags)
    return summary


def render_summary(summary: ContactSummary) -> str:
    head = (
        f"{summary.total} contacts ({summary.active} active, {summary.archived} archived), "
        f"{summary.never_contacted} never emailed, {summary.without_company} without a company"
    )
    parts = [head]
    for title, counts in (
        ("owner", summary.by_owner),
        ("source", summary.by_source),
        ("company", summary.by_company),
        ("tag", summary.by_tag),
    ):
        if counts:
            parts.append(counts_table(title, counts))
    return "\n\n".join(parts)
