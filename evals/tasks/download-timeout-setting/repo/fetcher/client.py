import time

from fetcher.config import Settings
from fetcher.transport import Transport


class Downloader:
    def __init__(self, settings: Settings | None = None, sleep=time.sleep, clock=time.monotonic):
        self.settings = settings or Settings()
        self.transport = Transport(
            self.settings.get("http.user_agent"), self.settings.seconds("http.connect_timeout")
        )
        self.sleep = sleep
        self.clock = clock

    def download(self, url: str) -> bytes:
        deadline = self.clock() + self.settings.seconds("http.timeout")
        attempts = self.settings.integer("http.retries") + 1
        backoff = self.settings.seconds("http.backoff")
        last_error: Exception | None = None
        for attempt in range(attempts):
            remaining = deadline - self.clock()
            if remaining <= 0:
                break
            try:
                return self._attempt(url, remaining)
            except OSError as exc:
                last_error = exc
                self.sleep(backoff * 2**attempt)
        raise TimeoutError(f"gave up on {url}") from last_error

    def _attempt(self, url: str, remaining: float) -> bytes:
        per_attempt = self.settings.seconds("http.attempt_timeout")
        return self.transport.fetch(url, timeout=min(per_attempt, remaining))
