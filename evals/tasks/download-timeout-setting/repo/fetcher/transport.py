"""The network layer. Tests swap `open_url` for a fake."""

import urllib.request

DEFAULT_TIMEOUT = 10.0


class Transport:
    def __init__(self, user_agent: str, connect_timeout: float) -> None:
        self.user_agent = user_agent
        self.connect_timeout = connect_timeout

    def open_url(self, url: str, timeout: float | None = None):
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        return urllib.request.urlopen(request, timeout=timeout or DEFAULT_TIMEOUT)

    def fetch(self, url: str, timeout: float | None = None) -> bytes:
        with self.open_url(url, timeout) as response:
            return response.read()
