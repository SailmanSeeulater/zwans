"""Deals: what the team hopes to sell, moving through the pipeline's stages."""

from orbit import ids
from orbit.errors import InvalidValue, NotFound
from orbit.models import CLOSED_STAGES, STAGES, Deal, StageChange
from orbit.payloads import deal_payload
from orbit.services.base import Service


class DealService(Service):
    def get(self, deal_id: str) -> Deal:
        row = self.store.get("deals", deal_id)
        if row is None:
            raise NotFound("deal", deal_id)
        return Deal.from_row(row)

    def all(self, stage: str | None = None, open_only: bool = False) -> list[Deal]:
        deals = [Deal.from_row(row) for row in self.store.rows("deals")]
        if stage is not None:
            deals = [deal for deal in deals if deal.stage == stage]
        if open_only:
            deals = [deal for deal in deals if deal.is_open]
        return deals

    def for_contact(self, contact_id: str) -> list[Deal]:
        return [deal for deal in self.all() if contact_id in deal.contact_ids]

    def create(
        self,
        title: str,
        amount: int = 0,
        contact_ids=(),
        company_id: str | None = None,
        owner: str = "",
        stage: str = "lead",
    ) -> Deal:
        title = " ".join(title.split())
        if not title:
            raise InvalidValue("A deal needs a title.")
        self._check_stage(stage)
        self._check_amount(amount)
        contacts = self._check_contacts(contact_ids)
        if company_id is not None and not self.store.has("companies", company_id):
            raise NotFound("company", company_id)
        now = self.clock()
        deal = Deal(
            id=ids.next_id(self.store, "deals"),
            title=title,
            amount=amount,
            stage=stage,
            contact_ids=contacts,
            company_id=company_id,
            owner=owner.strip(),
            created_at=now,
            updated_at=now,
            closed_at=now if stage in CLOSED_STAGES else None,
            stage_history=[StageChange(stage, now).to_row()],
        )
        self.store.put("deals", deal.to_row())
        self.publish("deal.created", deal_payload(deal), deal.contact_ids)
        return deal

    def move(self, deal_id: str, stage: str, contact_id: str | None = None) -> Deal:
        deal = self.get(deal_id)
        self._check_stage(stage)
        if stage == deal.stage:
            raise InvalidValue(f"{deal.id} is already at {stage}.")
        if contact_id is not None:
            if not self.store.has("contacts", contact_id):
                raise NotFound("contact", contact_id)
        previous = deal.stage
        now = self.clock()
        deal.stage = stage
        deal.updated_at = now
        deal.closed_at = now if stage in CLOSED_STAGES else None
        deal.stage_history.append(StageChange(stage, now, contact_id).to_row())
        self.store.put("deals", deal.to_row())
        payload = {
            "deal": deal_payload(deal),
            "from": previous,
            "to": stage,
            "contact_id": contact_id,
        }
        self.publish("deal.stage_changed", payload, deal.contact_ids)
        return deal

    def update(
        self,
        deal_id: str,
        *,
        title: str | None = None,
        amount: int | None = None,
        owner: str | None = None,
    ) -> Deal:
        deal = self.get(deal_id)
        if title is not None:
            title = " ".join(title.split())
            if not title:
                raise InvalidValue("A deal needs a title.")
            deal.title = title
        if amount is not None:
            self._check_amount(amount)
            deal.amount = amount
        if owner is not None:
            deal.owner = owner.strip()
        self.save(deal)
        return deal

    def add_contact(self, deal_id: str, contact_id: str) -> Deal:
        deal = self.get(deal_id)
        self._check_contacts([contact_id])
        if contact_id not in deal.contact_ids:
            deal.contact_ids.append(contact_id)
            self.save(deal)
        return deal

    def remove_contact(self, deal_id: str, contact_id: str) -> Deal:
        deal = self.get(deal_id)
        if contact_id in deal.contact_ids:
            deal.contact_ids.remove(contact_id)
            self.save(deal)
        return deal

    def save(self, deal: Deal) -> None:
        deal.updated_at = self.clock()
        self.store.put("deals", deal.to_row())
        self.publish("deal.updated", deal_payload(deal), deal.contact_ids)

    # -- checks -----------------------------------------------------------------------

    def _check_stage(self, stage: str) -> None:
        if stage not in STAGES:
            raise InvalidValue(f"Unknown stage {stage!r}; stages are {', '.join(STAGES)}.")

    def _check_amount(self, amount: int) -> None:
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise InvalidValue("A deal's amount is a whole number of cents, 0 or more.")

    def _check_contacts(self, contact_ids) -> list[str]:
        checked: list[str] = []
        for contact_id in contact_ids:
            if not self.store.has("contacts", contact_id):
                raise NotFound("contact", contact_id)
            if contact_id not in checked:
                checked.append(contact_id)
        return checked
