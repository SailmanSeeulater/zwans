"""Small text helpers shared by the services, the indexes and the importer."""

import re
import unicodedata

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TAG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def fold(text: str) -> str:
    """Lower case without accents: "Zoë Ångström" -> "zoe angstrom"."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def normalize_email(address: str) -> str:
    return address.strip().lower()


def is_email(address: str) -> bool:
    return bool(EMAIL.match(address.strip()))


def phone_digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def display_name(first: str, last: str) -> str:
    return " ".join(part for part in (first.strip(), last.strip()) if part)


def normalize_tag(tag: str) -> str:
    return "-".join(tag.strip().lower().split())


def is_tag(tag: str) -> bool:
    return bool(TAG.match(tag))


def clean_tags(tags) -> list[str]:
    """Tags as stored: normalized, checked, sorted, no repeats. Raises ValueError."""
    cleaned = set()
    for tag in tags:
        tag = normalize_tag(tag)
        if not is_tag(tag):
            raise ValueError(f"{tag!r} is not a valid tag (letters, digits, - and _).")
        cleaned.add(tag)
    return sorted(cleaned)


def unique(items, key=lambda item: item) -> list:
    """`items` without repeats, first occurrence wins, compared by `key`."""
    seen = set()
    kept = []
    for item in items:
        marker = key(item)
        if marker in seen:
            continue
        seen.add(marker)
        kept.append(item)
    return kept


def split_list(text: str, separator: str = ";") -> list[str]:
    return [part.strip() for part in text.split(separator) if part.strip()]


def shorten(text: str, width: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"
