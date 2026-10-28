"""What happens after account events. Importing this module wires the handlers up."""

from accounts.events import subscribe


@subscribe("PasswordReset")
def notify_user(event, context) -> None:
    context.mailer.send(event.user_id, "Your password was reset.")


@subscribe("PasswordChanged")
def log_password_change(event, context) -> None:
    context.audit.record(f"user:{event.user_id}", "password-changed")


@subscribe("CredentialEvent")
def audit_credentials(event, context) -> None:
    actor = "admin" if getattr(event, "by_admin", False) else f"user:{event.user_id}"
    context.audit.record(actor, "credentials", event=type(event).__name__)


@subscribe("SignedUp")
def welcome(event, context) -> None:
    context.mailer.send(event.user_id, f"Welcome, {event.email}!")
