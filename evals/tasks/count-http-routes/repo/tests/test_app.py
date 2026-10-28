from webapp.app import create_app


def test_routes_resolve() -> None:
    app = create_app()
    assert app.match("GET", "/api/users/42")(None) == "user (trailing slash)"
    assert app.match("HEAD", "/health")(None) == "ok"
    assert app.match("POST", "/api/orders/7/cancel")(None) == "cancelled"
    assert app.match("GET", "/api/admin/stats") is None
