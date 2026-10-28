from webapp import settings
from webapp.router import Router
from webapp.views import admin, orders, users


def health(request):
    return "ok"


def metrics(request):
    return "metrics"


def create_app() -> Router:
    app = Router()
    app.add("GET", "/health", health)
    app.add("GET", "/health/", health)
    api = Router()
    api.include("/users", users.router)
    api.include("/orders", orders.router)
    if settings.ENABLE_ADMIN:
        api.include("/admin", admin.router)
    app.include(settings.API_PREFIX, api)
    if settings.ENABLE_METRICS:
        app.add("GET", "/metrics", metrics)
        app.add("OPTIONS", "/metrics", metrics)
    return app
