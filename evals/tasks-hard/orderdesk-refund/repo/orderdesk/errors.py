"""Errors the domain raises on purpose.

Every error a user can cause is an OrderDeskError. The CLI turns them into a message on
stderr and the exit code below, so scripts can tell them apart.
"""


class OrderDeskError(Exception):
    exit_code = 1


class ValidationError(OrderDeskError):
    """The command makes no sense on its own (missing reason, negative amount...)."""

    exit_code = 2


class PermissionDenied(OrderDeskError):
    """The actor's role does not have the permission the command needs."""

    exit_code = 3


class InvalidState(OrderDeskError):
    """The command is fine, but not for an order in this state."""

    exit_code = 4


class NotFound(OrderDeskError):
    exit_code = 5


class ConcurrencyError(OrderDeskError):
    """Someone else appended to the order's stream since we loaded it."""

    exit_code = 6
