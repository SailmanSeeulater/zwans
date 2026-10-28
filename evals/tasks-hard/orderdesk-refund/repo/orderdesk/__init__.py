"""orderdesk: a small event-sourced order desk (orders, payments, shipping)."""

from .app import App, open_app

__all__ = ["App", "open_app"]
