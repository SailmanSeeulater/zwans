import json


def load_users(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["users"]


def count_active_users(path: str) -> int:
    return sum(1 for user in load_users(path) if user.get("active") is True)
