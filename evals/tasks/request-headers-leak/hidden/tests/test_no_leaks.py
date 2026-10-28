from api import create_post, get_profile, list_public_posts, search
from client import DEFAULT_HEADERS, build_request


def test_token_does_not_leak_into_anonymous_calls() -> None:
    get_profile("secret-token")

    assert "Authorization" not in list_public_posts().headers
    assert "Authorization" not in build_request("get", "https://x.test/").headers


def test_length_does_not_leak_into_later_calls() -> None:
    build_request("post", "https://x.test/", body=b"12345")

    assert "Content-Length" not in build_request("get", "https://x.test/").headers


def test_each_request_gets_its_own_headers() -> None:
    first = build_request("get", "https://x.test/a")
    second = build_request("get", "https://x.test/b")

    first.headers["X-Trace"] = "1"

    assert "X-Trace" not in second.headers


def test_defaults_are_left_alone() -> None:
    before = dict(DEFAULT_HEADERS)

    build_request("get", "https://x.test/", token="t0k3n", body=b"x")
    build_request("get", "https://x.test/")
    get_profile("another")
    create_post("t", "a", "b")

    assert before == DEFAULT_HEADERS


def test_callers_dict_is_not_modified() -> None:
    mine = {"Accept": "text/csv"}

    request = build_request("get", "https://x.test/", headers=mine, token="t", body=b"abc")

    assert mine == {"Accept": "text/csv"}
    assert request.headers["Accept"] == "text/csv"
    assert request.headers["Authorization"] == "Bearer t"
    assert request.headers["Content-Length"] == "3"


def test_search_language_does_not_stick() -> None:
    search("cats", language="de")

    assert "Accept-Language" not in search("dogs").headers
