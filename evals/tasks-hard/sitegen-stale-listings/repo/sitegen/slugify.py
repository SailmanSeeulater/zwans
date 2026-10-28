import re
import unicodedata
from functools import lru_cache

_SEPARATORS = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=4096)
def slugify(text: str) -> str:
    """'Hello, Wörld!' -> 'hello-world'."""
    text = text.replace("ß", "ss").replace("æ", "ae").replace("ø", "o")
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _SEPARATORS.sub("-", ascii_text.lower()).strip("-")
    return slug or "untitled"
