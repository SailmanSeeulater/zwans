from api import create_post, get_profile, list_public_posts, search


def test_public_posts_are_anonymous() -> None:
    request = list_public_posts()

    assert request.method == "GET"
    assert request.headers["Accept"] == "application/json"
    assert "Authorization" not in request.headers


def test_profile_sends_the_token() -> None:
    request = get_profile("abc123")

    assert request.headers["Authorization"] == "Bearer abc123"


def test_create_post_has_a_body() -> None:
    request = create_post("abc123", "Hi", "First post")

    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Content-Length"] == str(len(request.body or b""))


def test_search_with_language() -> None:
    request = search("cats", language="de")

    assert request.headers["Accept-Language"] == "de"
    assert request.headers["User-Agent"] == "acme-client/2.1"
