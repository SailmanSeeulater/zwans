"""The entry points the web layer calls."""

import hashlib

import accounts.handlers  # noqa: F401  (registers the event handlers)
from accounts.audit import AuditTrail
from accounts.events import PasswordReset, SignedUp, publish
from accounts.mailer import Outbox
from accounts.settings import load_settings
from accounts.sinks import make_sink


class AccountService:
    def __init__(self, settings: dict | None = None) -> None:
        self.settings = settings if settings is not None else load_settings()
        self.audit = AuditTrail(make_sink(self.settings))
        self.mailer = Outbox(self.settings["outbox_path"])
        self.passwords: dict[int, str] = {}
        self.emails: dict[int, str] = {}

    def sign_up(self, email: str, password: str) -> int:
        user_id = len(self.emails) + 1
        self.emails[user_id] = email
        self.passwords[user_id] = self._hash(password)
        publish(SignedUp(user_id, email), self)
        return user_id

    def reset_password(self, user_id: int, new_password: str, by_admin: bool = False) -> None:
        if user_id not in self.passwords:
            raise KeyError(user_id)
        self.passwords[user_id] = self._hash(new_password)
        publish(PasswordReset(user_id, by_admin), self)

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()
