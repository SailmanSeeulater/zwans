import json


def load_users(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["users"]
