from accounts.service import AccountService
from accounts.settings import load_settings


def test_reset_password_is_audited(tmp_path) -> None:
    settings = load_settings(profile="test", outbox_path=str(tmp_path / "outbox.txt"))
    service = AccountService(settings)
    user = service.sign_up("ada@example.org", "pw")
    service.audit._clock = lambda: 1700000000
    service.reset_password(user, "new", by_admin=True)
    assert service.audit._sink.lines == ["1700000000 admin credentials event=PasswordReset"]
