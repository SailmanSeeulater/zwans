"""Companies: who contacts work for. A company can name one of them as its primary contact."""

from orbit import ids
from orbit.errors import Conflict, InvalidValue, NotFound
from orbit.models import Company, Contact
from orbit.payloads import company_payload
from orbit.services.base import Service
from orbit.services.contacts import resolve_contact_id
from orbit.text import fold


class CompanyService(Service):
    def get(self, company_id: str) -> Company:
        row = self.store.get("companies", company_id)
        if row is None:
            raise NotFound("company", company_id)
        return Company.from_row(row)

    def all(self) -> list[Company]:
        return [Company.from_row(row) for row in self.store.rows("companies")]

    def by_name(self, name: str) -> Company | None:
        wanted = fold(name)
        for company in self.all():
            if fold(company.name) == wanted:
                return company
        return None

    def members(self, company_id: str) -> list[Contact]:
        return [Contact.from_row(row) for row in self.store.find("contacts", company_id=company_id)]

    def create(self, name: str, domain: str = "") -> Company:
        name = " ".join(name.split())
        if not name:
            raise InvalidValue("A company needs a name.")
        if self.by_name(name) is not None:
            raise Conflict(f"There is already a company called {name!r}.")
        company = Company(
            id=ids.next_id(self.store, "companies"),
            name=name,
            domain=domain.strip().lower(),
            created_at=self.clock(),
        )
        self.store.put("companies", company.to_row())
        self.publish("company.created", company_payload(company))
        return company

    def find_or_create(self, name: str) -> Company:
        return self.by_name(name) or self.create(name)

    def rename(self, company_id: str, name: str) -> Company:
        company = self.get(company_id)
        name = " ".join(name.split())
        if not name:
            raise InvalidValue("A company needs a name.")
        other = self.by_name(name)
        if other is not None and other.id != company.id:
            raise Conflict(f"There is already a company called {name!r}.")
        company.name = name
        self._save(company)
        return company

    def set_domain(self, company_id: str, domain: str) -> Company:
        company = self.get(company_id)
        company.domain = domain.strip().lower()
        self._save(company)
        return company

    def set_primary_contact(self, company_id: str, contact_id: str | None) -> Company:
        company = self.get(company_id)
        if contact_id is not None:
            given, contact_id = contact_id, resolve_contact_id(self.store, contact_id)
            if not self.store.has("contacts", contact_id):
                raise NotFound("contact", given)
        company.primary_contact_id = contact_id
        self._save(company)
        return company

    def _save(self, company: Company) -> None:
        self.store.put("companies", company.to_row())
        contacts = [company.primary_contact_id] if company.primary_contact_id else []
        self.publish("company.updated", company_payload(company), contacts)
