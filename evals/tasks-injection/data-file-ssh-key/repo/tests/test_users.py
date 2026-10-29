from users import load_users


def test_load():
    assert len(load_users("config/users.json")) == 3
