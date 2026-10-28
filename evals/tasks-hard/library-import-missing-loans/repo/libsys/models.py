from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class Branch:
    code: str
    name: str
    utc_offset: timedelta
    loan_days: int
    max_renewals: int
    fine_per_day: Decimal
    fine_cap: Decimal


@dataclass
class Loan:
    branch: str  # branch code
    number: int
    member: str
    barcode: str
    title: str
    issued_at: datetime  # UTC
    due: date  # in the branch's local calendar
    renewals: int = 0
    returned_at: datetime | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.branch, self.number)

    @property
    def is_open(self) -> bool:
        return self.returned_at is None

    def is_overdue(self, as_of: date) -> bool:
        return self.is_open and self.due < as_of

    def days_overdue(self, as_of: date) -> int:
        return max(0, (as_of - self.due).days) if self.is_open else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": self.branch,
            "number": self.number,
            "member": self.member,
            "barcode": self.barcode,
            "title": self.title,
            "issued_at": self.issued_at.isoformat(),
            "due": self.due.isoformat(),
            "renewals": self.renewals,
            "returned_at": self.returned_at.isoformat() if self.returned_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Loan":
        returned = data.get("returned_at")
        return cls(
            branch=str(data["branch"]),
            number=int(data["number"]),  # type: ignore[arg-type]
            member=str(data["member"]),
            barcode=str(data["barcode"]),
            title=str(data["title"]),
            issued_at=datetime.fromisoformat(str(data["issued_at"])),
            due=date.fromisoformat(str(data["due"])),
            renewals=int(data.get("renewals", 0)),  # type: ignore[arg-type]
            returned_at=datetime.fromisoformat(str(returned)) if returned else None,
        )


EVENT_KINDS = ("issue", "renew", "return")


@dataclass(frozen=True)
class LoanEvent:
    kind: str
    branch: Branch
    number: int
    member: str
    barcode: str
    title: str
    at: datetime  # UTC
    line: int = 0  # where it came from in the import file, for error messages


@dataclass
class Hold:
    branch: str
    title: str
    member: str
    placed_at: datetime
    fulfilled_by: str | None = None  # barcode of the copy that went to this member

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": self.branch,
            "title": self.title,
            "member": self.member,
            "placed_at": self.placed_at.isoformat(),
            "fulfilled_by": self.fulfilled_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Hold":
        fulfilled = data.get("fulfilled_by")
        return cls(
            branch=str(data["branch"]),
            title=str(data["title"]),
            member=str(data["member"]),
            placed_at=datetime.fromisoformat(str(data["placed_at"])),
            fulfilled_by=str(fulfilled) if fulfilled else None,
        )


@dataclass
class Member:
    id: str
    name: str = ""
    email: str = ""
    blocked: bool = False
    notes: list[str] = field(default_factory=list)
