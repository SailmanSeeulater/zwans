from tollgate.config import Route
from tollgate.routing import Router, normalize


def test_normalize() -> None:
    assert normalize("//orders///17/") == "/orders/17"
    assert normalize("/a/b?x=1//2") == "/a/b?x=1//2"
    assert normalize("") == "/"


def test_the_longest_prefix_wins() -> None:
    router = Router([Route("/", "web"), Route("/api", "api"), Route("/api/v2", "v2")])

    assert router.match("GET", "/api/v2/things").route.upstream == "v2"
    assert router.match("GET", "/api/v1/things").route.upstream == "api"
    assert router.match("GET", "/apis").route.upstream == "web"


def test_a_prefix_covers_itself_and_what_is_under_it() -> None:
    router = Router([Route("/orders", "orders")])

    assert router.match("GET", "/orders").found
    assert router.match("GET", "/orders/17?full=1").found
    assert not router.match("GET", "/ordersx").found
    assert not router.match("GET", "/").found


def test_methods() -> None:
    router = Router([Route("/orders", "orders", frozenset({"GET"}))])

    assert router.match("GET", "/orders").method_allowed
    assert not router.match("POST", "/orders").method_allowed


def test_strip_prefix() -> None:
    router = Router([])
    route = Route("/orders", "orders", None, True)

    assert router.upstream_path(route, "/orders/17?x=1") == "/17?x=1"
    assert router.upstream_path(route, "/orders") == "/"
    assert router.upstream_path(Route("/orders", "orders"), "/orders/17") == "/orders/17"
