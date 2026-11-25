"""deskline: a small helpdesk for small support teams."""

from .context import Context
from .desk import Desk
from .errors import Conflict, DesklineError, NotFound, ValidationError

__version__ = "1.4.0"

__all__ = ["Conflict", "Context", "Desk", "DesklineError", "NotFound", "ValidationError"]
