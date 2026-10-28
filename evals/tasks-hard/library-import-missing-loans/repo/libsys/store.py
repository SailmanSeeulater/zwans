"""Where the records live: a JSON file, loaded whole and saved whole."""

import json
import os
from collections.abc import Iterator
from pathlib import Path

from libsys.models import Hold, Loan, Member

FORMAT = 3


class StoreError(Exception):
    pass


class LibraryStore:
    def __init__(self) -> None:
        self.loans: dict[tuple[str, int], Loan] = {}
        self.holds: list[Hold] = []
        self.members: dict[str, Member] = {}

    # --- loans ----------------------------------------------------------------------

    def get_loan(self, branch: str, number: int) -> Loan | None:
        return self.loans.get((branch, number))

    def put_loan(self, loan: Loan) -> None:
        self.loans[loan.key] = loan

    def all_loans(self) -> Iterator[Loan]:
        return iter(sorted(self.loans.values(), key=lambda loan: loan.key))

    def open_loans(self) -> list[Loan]:
        return [loan for loan in self.all_loans() if loan.is_open]

    def loans_for_member(self, member: str) -> list[Loan]:
        loans = [loan for loan in self.loans.values() if loan.member == member]
        return sorted(loans, key=lambda loan: (loan.issued_at, loan.key))

    def copy_on_loan(self, barcode: str) -> Loan | None:
        for loan in self.loans.values():
            if loan.barcode == barcode and loan.is_open:
                return loan
        return None

    # --- members --------------------------------------------------------------------

    def member(self, member_id: str) -> Member:
        """The member with this id; members the desks mention are added on first sight."""
        if member_id not in self.members:
            self.members[member_id] = Member(member_id)
        return self.members[member_id]

    # --- files ----------------------------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        return {
            "format": FORMAT,
            "loans": [loan.to_dict() for loan in self.all_loans()],
            "holds": [hold.to_dict() for hold in self.holds],
            "members": [
                {
                    "id": m.id,
                    "name": m.name,
                    "email": m.email,
                    "blocked": m.blocked,
                    "notes": m.notes,
                }
                for m in sorted(self.members.values(), key=lambda m: m.id)
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "LibraryStore":
        if data.get("format") != FORMAT:
            raise StoreError(f"unsupported store format {data.get('format')!r}")
        store = cls()
        for item in data.get("loans", []):  # type: ignore[union-attr]
            store.put_loan(Loan.from_dict(item))
        store.holds = [Hold.from_dict(item) for item in data.get("holds", [])]  # type: ignore[union-attr]
        for item in data.get("members", []):  # type: ignore[union-attr]
            store.members[item["id"]] = Member(
                item["id"],
                item.get("name", ""),
                item.get("email", ""),
                bool(item.get("blocked", False)),
                list(item.get("notes", [])),
            )
        return store

    @classmethod
    def load(cls, path: Path) -> "LibraryStore":
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls()
        try:
            return cls.from_dict(json.loads(text))
        except (ValueError, KeyError, TypeError) as exc:
            raise StoreError(f"{path} is damaged: {exc}") from exc

    def save(self, path: Path) -> None:
        path = Path(path)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(self.to_dict(), indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, path)
