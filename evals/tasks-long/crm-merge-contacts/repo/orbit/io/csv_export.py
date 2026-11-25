"""Exporting contacts as CSV, in the same columns the importer reads, so an export can be
edited in a spreadsheet and imported back."""

import csv
import io

from orbit.io.csv_import import COLUMNS, FIELD_PREFIX


def export_contacts(crm, include_archived: bool = False) -> str:
    definitions = crm.fields.definitions()
    headers = [*COLUMNS, *(FIELD_PREFIX + d.name for d in definitions)]
    companies = {company.id: company.name for company in crm.companies.all()}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers)
    for contact in crm.contacts.all(include_archived):
        row = [
            contact.id,
            contact.first_name,
            contact.last_name,
            "; ".join(contact.emails),
            "; ".join(contact.phones),
            companies.get(contact.company_id, "") if contact.company_id else "",
            contact.title,
            contact.owner,
            contact.source,
            "; ".join(contact.tags),
        ]
        row += [crm.fields.render(d, contact.fields.get(d.name)) for d in definitions]
        writer.writerow(row)
    return out.getvalue()
