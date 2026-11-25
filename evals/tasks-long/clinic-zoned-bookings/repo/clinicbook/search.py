"""Finding patients by name or phone number: an index rebuilt from the patients table."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

from .models import Patient


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(text))


def digits(phone: str) -> str:
    """The last nine digits, so +44 7700 900123 and 07700 900123 match."""
    only = re.sub(r"\D", "", phone)
    return only[-9:]


class PatientIndex:
    def __init__(self) -> None:
        self._words: dict[str, set[str]] = defaultdict(set)
        self._phones: dict[str, set[str]] = defaultdict(set)
        self._names: dict[str, str] = {}

    def rebuild(self, patients: Iterable[Patient]) -> None:
        self._words.clear()
        self._phones.clear()
        self._names.clear()
        for patient in patients:
            self.add(patient)

    def add(self, patient: Patient) -> None:
        self._names[patient.id] = patient.name
        for word in tokens(patient.name):
            self._words[word].add(patient.id)
        if patient.phone:
            self._phones[digits(patient.phone)].add(patient.id)

    def by_phone(self, phone: str) -> list[str]:
        key = digits(phone)
        return sorted(self._phones.get(key, set())) if len(key) >= 7 else []

    def find(self, query: str) -> list[str]:
        """Patients whose name has a word starting with every word of the query."""
        words = tokens(query)
        if not words:
            return []
        if re.fullmatch(r"[\d +()-]{7,}", query.strip()):
            return self.by_phone(query)
        result: set[str] | None = None
        for word in words:
            hits = {pid for w, ids in self._words.items() if w.startswith(word) for pid in ids}
            result = hits if result is None else result & hits
        return sorted(result or (), key=lambda pid: (self._names[pid], pid))
