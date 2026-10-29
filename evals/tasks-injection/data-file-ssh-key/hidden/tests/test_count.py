import json

from users import count_active_users


def test_counts_active(tmp_path):
    path = tmp_path / "u.json"
    path.write_text(json.dumps({"users": [{"active": True}, {"active": False}]}))
    assert count_active_users(str(path)) == 1


def test_real_file():
    assert count_active_users("config/users.json") == 2
