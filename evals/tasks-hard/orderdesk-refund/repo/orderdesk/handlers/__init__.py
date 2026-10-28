"""Command handlers, one module per command.

Importing this package registers all of them, so every handler module must be imported
here.
"""

from . import cancel, note, pay, place, ship  # noqa: F401
