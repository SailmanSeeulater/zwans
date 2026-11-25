"""SKUs, barcodes, category slugs and other codes people type in."""

import re
import unicodedata

from shopdesk.errors import InvalidInput

_SKU = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WAREHOUSE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
_LIST = re.compile(r"^[a-z][a-z0-9_-]{0,29}$")


def normalize_sku(text: str) -> str:
    """SKUs are upper case, 1-40 characters of letters, digits, dot, dash and underscore,
    starting with a letter or digit."""
    sku = text.strip().upper()
    if not _SKU.match(sku):
        raise InvalidInput(f"{text!r} is not a valid SKU.")
    return sku


def normalize_slug(text: str) -> str:
    slug = text.strip().lower()
    if not _SLUG.match(slug):
        raise InvalidInput(f"{text!r} is not a valid category slug (try {slugify(text)!r}).")
    return slug


def slugify(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-") or "category"


def normalize_warehouse(text: str) -> str:
    code = text.strip().upper()
    if not _WAREHOUSE.match(code):
        raise InvalidInput(f"{text!r} is not a valid warehouse code (2-10 letters/digits).")
    return code


def normalize_list_name(text: str) -> str:
    name = text.strip().lower()
    if not _LIST.match(name):
        raise InvalidInput(f"{text!r} is not a valid price list name.")
    return name


def gtin_checksum(body: str) -> int:
    """The GS1 checksum for the digits before it (EAN-8, UPC-A, EAN-13, GTIN-14)."""
    total = 0
    for position, char in enumerate(reversed(body)):
        total += int(char) * (3 if position % 2 == 0 else 1)
    return (10 - total % 10) % 10


def normalize_barcode(text: str) -> str:
    """A GTIN: 8, 12, 13 or 14 digits with a correct checksum. Spaces and dashes are
    dropped; a 12-digit UPC-A is kept as typed."""
    code = re.sub(r"[\s-]", "", text)
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        raise InvalidInput(f"{text!r} is not a barcode (8, 12, 13 or 14 digits).")
    if gtin_checksum(code[:-1]) != int(code[-1]):
        raise InvalidInput(f"Barcode {code} has a wrong checksum.")
    return code
