import re


def slugify(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title)
    return "-".join(words).lower()
