import pytest

from fetcher.client import Downloader
from fetcher.config import Settings, parse_duration


def test_parse_duration() -> None:
    assert parse_duration("2m") == 120
    assert parse_duration("250ms") == 0.25


def test_retries_then_gives_up() -> None:
    calls = []

    def failing_fetch(url, timeout=None):
        calls.append(timeout)
        raise OSError("boom")

    downloader = Downloader(Settings({"FETCHER_PROFILE": "offline"}), sleep=lambda s: None)
    downloader.transport.fetch = failing_fetch
    with pytest.raises(TimeoutError):
        downloader.download("http://example.invalid/file")
    assert len(calls) == 1
