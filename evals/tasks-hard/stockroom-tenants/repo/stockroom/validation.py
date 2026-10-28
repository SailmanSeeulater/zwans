"""Input checks shared by the service, the importer and the CLI."""

import re

from .errors import InvalidInput

SKU = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
MAX_NAME = 80


def check_sku(sku: str) -> str:
    sku = sku.strip().upper()
    if not SKU.match(sku):
        raise InvalidInput(f"{sku!r} is not a valid SKU (2-32 letters, digits or dashes)")
    return sku


def check_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise InvalidInput("a product needs a name")
    if len(name) > MAX_NAME:
        raise InvalidInput(f"product names are at most {MAX_NAME} characters")
    return name


def check_positive(value: int, what: str) -> int:
    if value <= 0:
        raise InvalidInput(f"{what} must be more than zero")
    return value


def check_non_negative(value: int, what: str) -> int:
    if value < 0:
        raise InvalidInput(f"{what} cannot be negative")
    return value


def parse_cents(text: str) -> int:
    """'4.25' -> 425."""
    match = re.fullmatch(r"(\d+)(?:\.(\d{1,2}))?", text.strip())
    if match is None:
        raise InvalidInput(f"not an amount: {text!r}")
    whole, fraction = match.groups()
    return int(whole) * 100 + int((fraction or "0").ljust(2, "0"))


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
