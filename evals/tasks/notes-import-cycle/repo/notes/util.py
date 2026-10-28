import re
import unicodedata


def slugify(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-") or "untitled"


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())
