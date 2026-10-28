"""URL normalisation, so the same page is not bookmarked twice."""

from urllib.parse import urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def is_web_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in _DEFAULT_PORTS and bool(parts.netloc)


def normalize_url(url: str) -> str:
    """Lowercase scheme and host, no default port, no fragment, no trailing slash on the path.

    'HTTPS://Example.com:443/a/#top' -> 'https://example.com/a'
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if parts.port and parts.port != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, host, path, parts.query, ""))
